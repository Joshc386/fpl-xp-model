// Reads one published CSV from BasePath and promotes its header row.
// A web path uses Web.Contents; a local folder uses File.Contents.
(file as text) as table =>
let
    path = BasePath & file,
    source = if Text.StartsWith(BasePath, "https://") then Web.Contents(path) else File.Contents(path),
    csv = Csv.Document(source, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    promoted = Table.PromoteHeaders(csv, [PromoteAllScalars = true])
in
    promoted
