// players.csv -> tbl_players. Types follow docs/data_contract.md; "en-US" fixes the
// decimal point whatever the user's regional settings. Blank news and chance_next stay null.
let
    source = GetCsv("players.csv"),
    typed = Table.TransformColumnTypes(source, {
        {"player_id", Int64.Type}, {"web_name", type text}, {"team", type text},
        {"position", type text}, {"price_m", type number}, {"status", type text},
        {"chance_next", type number}, {"news", type text}, {"selected_pct", type number},
        {"minutes", Int64.Type}, {"starts", Int64.Type}, {"total_points", Int64.Type},
        {"ppg", type number}, {"xg90", type number}, {"xa90", type number},
        {"dc90", type number}, {"pen_taker", type logical}, {"net_transfers_gw", Int64.Type},
        {"price_change_gw", type number}, {"price_change_start", type number}
    }, "en-US")
in
    typed
