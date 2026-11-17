// The one base path every query reads from. It must end with a separator.
// Release: the raw GitHub URL of outputs/. For development, build_workbook.py
// --base-path swaps in a local folder (for example C:\Temp\outputs\).
"https://raw.githubusercontent.com/Joshc386/fpl-xp-model/main/outputs/" meta [IsParameterQuery = true, IsParameterQueryRequired = true, Type = "Text"]
