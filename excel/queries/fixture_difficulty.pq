// fixture_difficulty.csv -> tbl_fixtures. A double gameweek has two rows per team and a
// blank gameweek none; nothing is summed or filled here.
let
    source = GetCsv("fixture_difficulty.csv"),
    typed = Table.TransformColumnTypes(source, {
        {"team_id", Int64.Type}, {"team", type text}, {"match_id", type text},
        {"gw", Int64.Type}, {"opponent_id", Int64.Type}, {"opponent", type text},
        {"home", type logical}, {"lambda_for", type number},
        {"lambda_against", type number}, {"p_cs", type number}
    }, "en-US")
in
    typed
