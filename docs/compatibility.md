# Supported formats and limits

This version deliberately rejects ambiguous or unsupported transfers. A printer
appearing in the profile list does not mean every project can be transferred to
it successfully.

| Area | Supported behavior / limit |
| --- | --- |
| Input | Editable Orca/Bambu 3MF ZIP project with `Metadata/project_settings.config` and native 3MF model data |
| Other 3MF writers | Arbitrary PrusaSlicer, Cura, mesh-only, and unrelated 3MF layouts are not translated |
| Sliced-only downloads | G-code-only archives are rejected; editable inputs lose stale sliced G-code |
| Plates | One plate; multi-plate projects are rejected in this version |
| Hardware | Single physical nozzle; IDEX, independent multiple extruders, and tool changers are not converted |
| Filaments | Multiple logical slots remain multiple slots; Standard/High Flow option variants are not treated as extra physical extruders |
| Nozzle diameter | Any diameter is allowed when the source and target match; changing nozzle diameter is rejected |
| Extruder variants | Each target variant needs matching source tuning for every logical material slot; missing tuning is rejected |
| Geometry | Existing placement is retained; conservative bounding rectangles include modifiers and must fit the target convex polygon, excluded areas, and height; concave beds are rejected; no automatic arranging, centering, scaling, or cutting |
| Units | Millimeters only |
| Input size | Up to 512 MB compressed, 2 GB total expanded, and 10,000 ZIP members; metadata up to 16 MB and each model XML up to 128 MB |
| Settings | Printer-owned option classification comes from Orca 2.4.1; later or fork-specific options may require a schema update |
| Network printing | Never attempted; saved local connection settings stay in Orca |
| Slicing | Not performed; a successful transfer does not certify the slicer's output or actual hardware safety |

Geometry checks cover models and modifiers. They do not include generated
supports, brims, purge towers, toolhead clearance, or eventual toolpaths.

## Profile identity and inheritance

The config directory is the OrcaSlicer data root containing `user` and, usually,
`system`. Platform discovery checks normal Windows, macOS, Linux/XDG, and Linux
Flatpak locations. Portable/custom locations can be selected manually. An
AppImage is not unpacked or executed by the tool; provide its accessible
`resources/profiles` directory if the required parents are absent locally.

Profiles can inherit several parent profiles. Resolution uses vendor context and
the selected account. Duplicate display names must not be silently joined across
vendors or accounts. Missing parents, cycles, and unresolved ambiguity produce
errors. A user account identifier may be needed locally for selection, but is
not part of the public repository or synthetic examples.

Printer inheritance containing nil/null overrides is rejected because this
version requires explicit printer values. A child profile that changes or
reorders its parent's extruder-variant layout is also rejected. These restrictions
apply to printer profiles; supported nullable source filament overrides are
preserved.

The target's explicit printer configuration is applied after removing recognized
source printer settings. If a printer-owned option is absent from the entire
target chain, it is omitted so the installed Orca version can use its own
defaults. This avoids silently inheriting a source machine's motion limits,
start/end templates, or physical dimensions.

Project hardware selectors and feeder metadata are reset for the selected
single-nozzle target. The active nozzle variant follows the target default,
physical nozzle mappings point to that nozzle, and source AMS-count metadata is
omitted. Logical filament slot numbers and their per-object assignments remain
unchanged. Recheck physical feeder assignments in Orca before printing.

Orca deliberately excludes credentials and addresses when loading external
presets, but it can still apply non-secret connection selectors. The converter
preserves target preset identity and the target's host, plugin, and
authentication-method selectors, while excluding credentials and machine
addresses from the project. This preserves the selected profile's connection
handling without exporting its secrets. Matching a display name alone is
insufficient evidence that a connection will work; confirm the saved printer in
Orca.

## Plates and materials

The default plate comes from the selected printer profile, when declared and
recognized. Otherwise choose a plate explicitly. There is no universal
Textured PEI or machine-specific fallback. Choosing a plate does not synthesize
filament temperatures: the source filament tuning is retained. Verify that it
has suitable temperatures for the chosen plate and hardware.

The plate menu lists Orca's known plate names; it is not a list of plates that
are physically compatible with the selected printer. Choose the plate actually
fitted to your machine.

Logical filament slots and extruder variants describe different things. A project
may have two filament slots with separate Standard/High Flow values for each.
Those values are not evidence of a four-nozzle machine. The transfer retains the
logical assignments and variant tuning, and rejects genuinely unsupported
physical extruder layouts.

Multi-material assignments do not establish that the target can automatically
change material. AMS/MMU availability, filament loading, firmware behavior, and
manual changes must be checked in Orca and on the printer.

## Preserved content and trust boundary

Untouched archive members are copied without altering their uncompressed bytes.
Geometry, object settings, modifiers, painting, and placement are retained within
the supported format. Edited settings metadata is serialized again; preserving
its values does not imply byte-identical JSON formatting. Printer identity,
plate/compatibility metadata, and known sensitive fields are intentional changes.

The engine performs bounded ZIP/XML/JSON parsing and writes a new archive. It
does not execute source or target templates, extract files into Orca's folders,
or run embedded G-code. Some settings contain G-code templates by design. Review
templates from an untrusted download before slicing or printing.

The output is not an anonymized model. Arbitrary names, author information,
embedded previews, and user-authored text can remain. Do not use a converted
project as evidence that a file is safe to publish.

## Native validation

Synthetic tests check data preservation and rejection behavior. They cannot
prove that a particular installed Orca version will load every setting exactly as
intended. In one Orca 2.4.1 environment, passing a project to a newly launched
instance reset PLA/TPU filaments to Generic ASA; opening the same project with
File > Open inside an already-running instance retained them. An Orca-native
saved project exhibited the same startup reset. This converter therefore does
not auto-launch Orca or claim that ZIP checks establish native success.

Before printing, open the result as a project, confirm the saved target profile,
plate, material slots and tuning, then slice and inspect all layers. Runtime
testing on macOS/Linux and on additional printer families remains necessary even
when the portable code and CI tests pass.
