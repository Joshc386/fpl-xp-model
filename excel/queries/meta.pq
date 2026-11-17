// meta.csv -> tbl_meta (one row). The two UTC timestamps load as UTC date-times.
// The backtest MAEs are null until the first backtest.
let
    source = GetCsv("meta.csv"),
    typed = Table.TransformColumnTypes(source, {
        {"run_utc", type text}, {"upstream_commit", type text}, {"current_gw", Int64.Type},
        {"next_gw", Int64.Type}, {"next_deadline_utc", type text}, {"model_version", type text},
        {"max_horizon", Int64.Type}, {"backtest_mae_model", type number},
        {"backtest_mae_ep_next", type number}, {"status", type text}
    }, "en-US"),
    utc = Table.TransformColumns(typed, {
        {"run_utc", each DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(DateTimeZone.FromText(_), 0)), type datetime},
        {"next_deadline_utc", each DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(DateTimeZone.FromText(_), 0)), type datetime}
    })
in
    utc
