// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only logging shim. The production P5 router uses vendor common/logging.h.
#pragma once
#define LOG_WARNING(category, ...) do { } while (false)
