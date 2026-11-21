/*****************************************************************************
 * PokerTH - The open source texas holdem engine                             *
 * Copyright (C) 2006-2026 Felix Hammer, Florian Thauer, Lothar May          *
 *                                                                           *
 * This program is free software: you can redistribute it and/or modify      *
 * it under the terms of the GNU Affero General Public License as            *
 * published by the Free Software Foundation, either version 3 of the        *
 * License, or (at your option) any later version.                           *
 *****************************************************************************/
/*
 * Managed ("platform") mode for the dedicated server.
 *
 * In this mode the server does not run a public lobby. A separate platform
 * service sells seats; each player connects with a short-lived seat token
 * (an Ed25519-signed JWT) instead of a password. The token names the player,
 * the platform table and the table settings, so the server can create the
 * game itself when the first seat-holder arrives. When the game ends the
 * server posts the finishing order back to the platform (HMAC-signed).
 *
 * Configuration (environment variables):
 *   POKERTH_PLATFORM_MODE=1                 enable managed mode
 *   POKERTH_SEAT_TOKEN_PUBLIC_KEY=<PEM>     Ed25519 public key (or ..._FILE=<path>)
 *   POKERTH_PLATFORM_URL=http://host:port   where results are posted
 *   POKERTH_PLATFORM_SECRET=<secret>        shared HMAC-SHA256 secret
 *   POKERTH_PLATFORM_START_TIMEOUT_SEC=120  start with whoever came after this
 *   POKERTH_PLATFORM_SPOOL_DIR=<dir>         where unsent results are kept (mount a volume)
 *   POKERTH_WS_ORIGIN=play.example.com       allowed browser origin (http and https)
 */

#ifndef _PLATFORM_H_
#define _PLATFORM_H_

#include <boost/shared_ptr.hpp>
#include <map>
#include <string>
#include <vector>

namespace platform
{

struct SeatClaims {
	std::string userId;    // platform user id (sub)
	std::string username;  // display name at the table (name)
	std::string tableId;   // platform table id (tbl)
	std::string gameRef;   // platform game reference (game)
	std::string title;     // table title shown to players
	int players = 0;       // players seated by the platform (game starts when all are in)
	int startingChips = 0;
	int firstSmallBlind = 0;
	int blindLevelMinutes = 0;
	int bots = 0;          // computer players filling the other seats (practice tables)
};

// True when POKERTH_PLATFORM_MODE=1.
bool Enabled();

// Seconds to wait for every seated player before starting with those present.
int StartTimeoutSec();

// Verify signature, issuer, audience and expiry. Returns null if invalid;
// the reason is written to the server log.
boost::shared_ptr<SeatClaims> VerifySeatToken(const std::string &token);

// Post the finishing order (platform user ids, winner first) for a table.
// The result is stored on disk first (POKERTH_PLATFORM_SPOOL_DIR, default
// ~/.pokerth/platform-results) and sent in the background until the platform
// answers; a rejected result is kept as <table>.json.rejected.
// `places` = each player's real place (1 = winner), counting computer players.
void ReportResult(const std::string &tableId, const std::vector<std::string> &finishingOrder,
				  const std::map<std::string, int> &places = std::map<std::string, int>());

// At start-up: resend results stored by a previous run that were never accepted.
void ResendPendingResults();

} // namespace platform

#endif
