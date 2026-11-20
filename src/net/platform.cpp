/*****************************************************************************
 * PokerTH - The open source texas holdem engine                             *
 * Copyright (C) 2006-2026 Felix Hammer, Florian Thauer, Lothar May          *
 *                                                                           *
 * This program is free software: you can redistribute it and/or modify      *
 * it under the terms of the GNU Affero General Public License as            *
 * published by the Free Software Foundation, either version 3 of the        *
 * License, or (at your option) any later version.                           *
 *****************************************************************************/

#include <net/platform.h>
#include <core/loghelper.h>

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/json.hpp>
// Boost.JSON is used header-only; this translation unit carries its implementation.
#include <boost/json/src.hpp>

#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/pem.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <thread>

namespace platform
{

namespace
{

std::string Env(const char *name)
{
	const char *v = std::getenv(name);
	return v ? std::string(v) : std::string();
}

std::string PublicKeyPem()
{
	std::string pem = Env("POKERTH_SEAT_TOKEN_PUBLIC_KEY");
	if (pem.empty()) {
		const std::string path = Env("POKERTH_SEAT_TOKEN_PUBLIC_KEY_FILE");
		if (!path.empty()) {
			std::ifstream in(path);
			std::stringstream ss;
			ss << in.rdbuf();
			pem = ss.str();
		}
	}
	return pem;
}

// Loaded once; Ed25519 verification needs no per-call state.
EVP_PKEY *PublicKey()
{
	static std::once_flag once;
	static EVP_PKEY *key = nullptr;
	std::call_once(once, [] {
		const std::string pem = PublicKeyPem();
		if (pem.empty()) {
			LOG_ERROR("platform: POKERTH_SEAT_TOKEN_PUBLIC_KEY is not set; every seat token will be rejected");
			return;
		}
		BIO *bio = BIO_new_mem_buf(pem.data(), static_cast<int>(pem.size()));
		key = PEM_read_bio_PUBKEY(bio, nullptr, nullptr, nullptr);
		BIO_free(bio);
		if (!key || EVP_PKEY_get_id(key) != EVP_PKEY_ED25519) {
			LOG_ERROR("platform: seat token public key is not a valid Ed25519 PEM key");
			if (key)
				EVP_PKEY_free(key);
			key = nullptr;
		}
	});
	return key;
}

bool Base64UrlDecode(const std::string &in, std::string &out)
{
	static const std::string chars =
		"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
	out.clear();
	unsigned buf = 0;
	int bits = 0;
	for (char c : in) {
		if (c == '=')
			break;
		const std::string::size_type pos = chars.find(c);
		if (pos == std::string::npos)
			return false;
		buf = (buf << 6) | static_cast<unsigned>(pos);
		bits += 6;
		if (bits >= 8) {
			bits -= 8;
			out.push_back(static_cast<char>((buf >> bits) & 0xFF));
		}
	}
	return true;
}

std::string GetString(const boost::json::object &o, const char *key)
{
	const boost::json::value *v = o.if_contains(key);
	return (v && v->is_string()) ? std::string(v->as_string().c_str()) : std::string();
}

int GetInt(const boost::json::object &o, const char *key, int fallback)
{
	const boost::json::value *v = o.if_contains(key);
	if (v && v->is_int64())
		return static_cast<int>(v->as_int64());
	if (v && v->is_uint64())
		return static_cast<int>(v->as_uint64());
	return fallback;
}

std::string HexHmacSha256(const std::string &key, const std::string &data)
{
	unsigned char out[EVP_MAX_MD_SIZE];
	unsigned int len = 0;
	HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()),
		 reinterpret_cast<const unsigned char *>(data.data()), data.size(), out, &len);
	static const char *hex = "0123456789abcdef";
	std::string result;
	for (unsigned i = 0; i < len; ++i) {
		result.push_back(hex[out[i] >> 4]);
		result.push_back(hex[out[i] & 0xF]);
	}
	return result;
}

struct Url {
	std::string host, port, path;
};

bool ParseHttpUrl(const std::string &url, Url &out)
{
	const std::string scheme = "http://";
	if (url.compare(0, scheme.size(), scheme) != 0)
		return false;
	std::string rest = url.substr(scheme.size());
	const std::string::size_type slash = rest.find('/');
	out.path = slash == std::string::npos ? std::string() : rest.substr(slash);
	std::string hostport = rest.substr(0, slash);
	const std::string::size_type colon = hostport.rfind(':');
	out.host = colon == std::string::npos ? hostport : hostport.substr(0, colon);
	out.port = colon == std::string::npos ? "80" : hostport.substr(colon + 1);
	if (!out.path.empty() && out.path.back() == '/')
		out.path.pop_back();
	return !out.host.empty();
}

// One HTTP attempt. Returns the status code, or 0 on a network error.
int PostOnce(const Url &url, const std::string &target, const std::string &body, const std::string &signature)
{
	namespace http = boost::beast::http;
	try {
		boost::asio::io_context ioc;
		boost::asio::ip::tcp::resolver resolver(ioc);
		boost::beast::tcp_stream stream(ioc);
		stream.expires_after(std::chrono::seconds(15));
		stream.connect(resolver.resolve(url.host, url.port));

		http::request<http::string_body> req(http::verb::post, target, 11);
		req.set(http::field::host, url.host);
		req.set(http::field::content_type, "application/json");
		req.set("X-Signature", signature);
		req.body() = body;
		req.prepare_payload();
		http::write(stream, req);

		boost::beast::flat_buffer buffer;
		http::response<http::string_body> res;
		http::read(stream, buffer, res);
		boost::system::error_code ec;
		stream.socket().shutdown(boost::asio::ip::tcp::socket::shutdown_both, ec);
		if (res.result_int() >= 300) {
			LOG_ERROR("platform: result post answered " << res.result_int() << ": " << res.body());
		}
		return static_cast<int>(res.result_int());
	} catch (const std::exception &e) {
		LOG_ERROR("platform: result post failed: " << e.what());
		return 0;
	}
}

} // namespace

bool Enabled()
{
	static const bool enabled = Env("POKERTH_PLATFORM_MODE") == "1";
	return enabled;
}

int StartTimeoutSec()
{
	const std::string v = Env("POKERTH_PLATFORM_START_TIMEOUT_SEC");
	const int sec = v.empty() ? 120 : std::atoi(v.c_str());
	return sec > 0 ? sec : 120;
}

boost::shared_ptr<SeatClaims> VerifySeatToken(const std::string &token)
{
	boost::shared_ptr<SeatClaims> none;
	EVP_PKEY *key = PublicKey();
	if (!key || token.size() > 4096)
		return none;

	const std::string::size_type d1 = token.find('.');
	const std::string::size_type d2 = d1 == std::string::npos ? d1 : token.find('.', d1 + 1);
	if (d1 == std::string::npos || d2 == std::string::npos)
		return none;

	std::string header, payload, signature;
	if (!Base64UrlDecode(token.substr(0, d1), header)
			|| !Base64UrlDecode(token.substr(d1 + 1, d2 - d1 - 1), payload)
			|| !Base64UrlDecode(token.substr(d2 + 1), signature)) {
		return none;
	}

	try {
		const boost::json::object h = boost::json::parse(header).as_object();
		if (GetString(h, "alg") != "EdDSA") {
			LOG_MSG("platform: rejected seat token with alg " << GetString(h, "alg"));
			return none;
		}
	} catch (...) {
		return none;
	}

	// Signature covers "<header>.<payload>" as sent (base64url text).
	const std::string signedPart = token.substr(0, d2);
	EVP_MD_CTX *ctx = EVP_MD_CTX_new();
	bool ok = ctx
			  && EVP_DigestVerifyInit(ctx, nullptr, nullptr, nullptr, key) == 1
			  && EVP_DigestVerify(ctx,
								  reinterpret_cast<const unsigned char *>(signature.data()), signature.size(),
								  reinterpret_cast<const unsigned char *>(signedPart.data()), signedPart.size()) == 1;
	EVP_MD_CTX_free(ctx);
	if (!ok) {
		LOG_MSG("platform: rejected seat token with a bad signature");
		return none;
	}

	try {
		const boost::json::object c = boost::json::parse(payload).as_object();
		const long long now = std::chrono::duration_cast<std::chrono::seconds>(
								  std::chrono::system_clock::now().time_since_epoch()).count();
		const boost::json::value *exp = c.if_contains("exp");
		if (!exp || !exp->is_number() || exp->to_number<long long>() <= now) {
			LOG_MSG("platform: rejected expired seat token");
			return none;
		}
		if (GetString(c, "iss") != "platform" || GetString(c, "aud") != "game-server") {
			LOG_MSG("platform: rejected seat token with wrong issuer or audience");
			return none;
		}
		boost::shared_ptr<SeatClaims> claims(new SeatClaims);
		claims->userId = GetString(c, "sub");
		claims->username = GetString(c, "name");
		claims->tableId = GetString(c, "tbl");
		claims->gameRef = GetString(c, "game");
		const boost::json::value *cfgValue = c.if_contains("cfg");
		if (!cfgValue || !cfgValue->is_object()) {
			LOG_MSG("platform: rejected seat token without table settings");
			return none;
		}
		const boost::json::object &cfg = cfgValue->as_object();
		claims->title = GetString(cfg, "title");
		claims->players = GetInt(cfg, "players", 0);
		claims->startingChips = GetInt(cfg, "chips", 0);
		claims->firstSmallBlind = GetInt(cfg, "sb", 0);
		claims->blindLevelMinutes = GetInt(cfg, "blind_minutes", 5);
		if (claims->userId.empty() || claims->username.empty() || claims->tableId.empty()
				|| claims->players < 2 || claims->players > 10
				|| claims->startingChips <= 0 || claims->firstSmallBlind <= 0) {
			LOG_MSG("platform: rejected seat token with incomplete claims");
			return none;
		}
		return claims;
	} catch (...) {
		return none;
	}
}

void ReportResult(const std::string &tableId, const std::vector<std::string> &finishingOrder)
{
	Url url;
	const std::string base = Env("POKERTH_PLATFORM_URL");
	const std::string secret = Env("POKERTH_PLATFORM_SECRET");
	if (!ParseHttpUrl(base, url) || secret.empty()) {
		LOG_ERROR("platform: cannot report table " << tableId
				  << " - POKERTH_PLATFORM_URL (http://...) and POKERTH_PLATFORM_SECRET must be set");
		return;
	}

	boost::json::array order;
	for (const std::string &id : finishingOrder)
		order.emplace_back(id);
	boost::json::object root;
	root["finishing_order"] = std::move(order);
	const std::string body = boost::json::serialize(root);
	const std::string target = url.path + "/internal/games/" + tableId + "/result";
	const std::string signature = HexHmacSha256(secret, body);

	LOG_MSG("platform: reporting result for table " << tableId << " (" << finishingOrder.size() << " players)");
	std::thread([url, target, body, signature, tableId] {
		for (int attempt = 0; attempt < 12; ++attempt) {
			const int status = PostOnce(url, target, body, signature);
			if (status >= 200 && status < 300) {
				LOG_MSG("platform: result for table " << tableId << " accepted");
				return;
			}
			if (status >= 400 && status < 500 && status != 409 && status != 429) {
				LOG_ERROR("platform: result for table " << tableId << " rejected (" << status << "), not retrying");
				return;
			}
			std::this_thread::sleep_for(std::chrono::seconds(std::min(60, 1 << attempt)));
		}
		LOG_ERROR("platform: giving up reporting table " << tableId << "; the platform's admin must settle it");
	}).detach();
}

} // namespace platform
