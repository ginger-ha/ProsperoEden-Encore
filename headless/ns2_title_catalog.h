// SPDX-License-Identifier: GPL-3.0-or-later
// Offline Nintendo Switch 2 title identity fallback for games whose extracted
// Control NCA/NACP and Nlib Switch 1 database are unavailable.
// Names: https://www.switchbrew.org/wiki/Switch_2:Title_list/Games
// Cover URL sources: vendor-owned retail product images, fetched by launcher
// on demand (no copyrighted artwork is redistributed in this repository).
#pragma once
#include <array>
#include <cstdint>
#include <string_view>

namespace Eden::Ns2Catalog {
struct Entry {
    std::uint64_t id;
    std::string_view name;
    std::string_view publisher;
    std::string_view release_date;
    std::string_view genre;
    std::string_view front_host;
    std::string_view front_path;
};
inline constexpr std::array<Entry, 18> kTitles{{
    {0x040003901FBC2000ULL, "Survival Kids", "", "", "", "", ""},
    {0x0400303021AAC000ULL, "DELTARUNE", "", "", "", "", ""},
    {0x040052E01D3DA000ULL, "Nintendo GameCube - Nintendo Classics", "", "", "", "", ""},
    {0x040057C02159A000ULL, "Nintendo Switch 2 Welcome Tour", "", "", "", "", ""},
    {0x04006CC0223D2000ULL, "HITMAN World of Assassination - Signature Edition", "", "", "", "", ""},
    {0x040074A01BF12000ULL, "Donkey Kong Bananza", "Nintendo", "2025-07-17", "Action · Plateformes",
        "https://www.powerplanetonline.com", "/cdnassets/products/96599/donkey_kong_bananza_1_l.jpg"},
    {0x040077201BE50000ULL, "Kirby Air Riders", "", "", "", "", ""},
    {0x040078001CCF6000ULL, "Street Fighter 6", "", "", "", "", ""},
    {0x0400813022B32000ULL, "Fortnite", "", "", "", "", ""},
    {0x040082902313C000ULL, "Arcade Archives 2 RIDGE RACER", "", "", "", "", ""},
    {0x04009570209F8000ULL, "Hogwarts Legacy", "", "", "", "", ""},
    {0x0400A4802437E000ULL, "Drag x Drive: Global Jam", "", "", "", "", ""},
    {0x0400BBB020FF0000ULL, "Yakuza 0 Director's Cut", "", "", "", "", ""},
    {0x0400C3F00006E000ULL, "Mario Kart World", "Nintendo", "2025-06-05", "Course · Fête",
        "https://www.euronics.ee", "/UserFiles/Products/Images/416246-626247.jpg"},
    {0x0400CA40208C8000ULL, "Split Fiction", "", "", "", "", ""},
    {0x0400CBA0221EA000ULL, "BRAVELY DEFAULT FLYING FAIRY HD Remaster", "", "", "", "", ""},
    {0x0400DDB020648000ULL, "Cyberpunk 2077: Ultimate Edition", "", "", "", "", ""},
    {0x0400E140216D4000ULL, "SONIC X SHADOW GENERATIONS", "", "", "", "", ""},
}};
inline const Entry* Find(std::uint64_t id) noexcept {
    for (const auto& item : kTitles)
        if (item.id == id) return &item;
    return nullptr;
}
}  // namespace Eden::Ns2Catalog
