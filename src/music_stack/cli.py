"""The ``music-stack`` command line.

Command groups mirror the pipeline: ``project`` scaffolds a song, ``audio``
prepares it locally, and one group per service does the remote work. Every
command that spends money or credits is separate from the commands that only
read — ``workflows`` and ``models`` exist so you can look before you pay.
"""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, audio, brief, local_tools, projects
from .adapters import kits as kits_adapter
from .adapters import moises as moises_adapter
from .adapters import music_ai as music_ai_adapter
from .adapters import suno as suno_adapter
from .config import Settings
from .errors import MusicStackError


def _print_json(payload):
    print(json.dumps(payload, indent=2, default=str))


# -- doctor ---------------------------------------------------------------


def cmd_doctor(args, settings):
    """Report local tooling and credential presence. Never prints a secret."""
    print("music-stack {}".format(__version__))
    print("root: {}".format(settings.root))
    print("projects: {}".format(settings.projects_dir))

    print("\nLocal tools")
    ok = True
    for binary in ("ffmpeg", "ffprobe"):
        found = audio.which(binary)
        print("  {:<10} {}".format(binary, found or "MISSING — brew install ffmpeg"))
        ok = ok and bool(found)

    print("\nCredentials (presence only; values are never displayed)")
    for service, name, configured, fp in settings.describe():
        print(
            "  {:<9} {:<18} {:<12} {}".format(
                service, name, "configured" if configured else "missing", fp
            )
        )

    print("\nServices")
    suno = suno_adapter.status(settings)
    print("  suno      {}".format(suno["status"]))
    unverified = [k for k, (_, v) in kits_adapter.ENDPOINTS.items() if not v]
    if unverified:
        print(
            "  kits      endpoint paths unverified: {}".format(", ".join(unverified))
        )
        print("            (confirm against docs.kits.ai; see docs/troubleshooting.md)")

    if not ok:
        print("\nffmpeg is required for the audio commands. Run ./scripts/bootstrap-macos.sh")
    return 0 if ok else 1


# -- project --------------------------------------------------------------


def cmd_project_new(args, settings):
    path = projects.create(settings.projects_dir, args.title, exist_ok=args.exist_ok)
    print("Created {}".format(path))
    for sub in projects.SUBDIRS:
        print("  {}/".format(sub))
    return 0


def cmd_project_list(args, settings):
    found = projects.listing(settings.projects_dir)
    if not found:
        print("No projects yet. Create one:\n  music-stack project new \"Working Title\"")
        return 0
    for slug in found:
        print(slug)
    return 0


# -- audio ----------------------------------------------------------------


def cmd_audio_normalize(args, settings):
    dest = audio.normalize(
        args.src,
        args.dest,
        rate=args.rate,
        bit_depth=args.bit_depth,
        overwrite=args.overwrite,
    )
    print("Wrote {}".format(dest))
    return 0


def cmd_audio_inspect(args, settings):
    data = audio.inspect(args.path)
    _print_json(data["summary"] if not args.full else data)
    return 0


# -- analyze (the one command) --------------------------------------------


def cmd_analyze(args, settings):
    """Everything, in one pass, using whatever this machine has."""
    result = brief.analyze(
        settings.projects_dir,
        args.input,
        title=args.title,
        skip=tuple(args.skip or ()),
        dry_run=args.dry_run,
    )
    if args.dry_run:
        _print_json(result)
        return 0
    print("\n" + "=" * 60)
    print(result["brief"])
    print("=" * 60)
    print("\nWritten to {}".format(result["brief_path"]))
    return 0


# -- local ----------------------------------------------------------------


def _emit(result):
    """Print a local-tool result: the command, then whatever it produced."""
    print("$ {}".format(" ".join(result["command"])))
    if result.get("cwd"):
        print("  (run from {})".format(result["cwd"]))
    for path in result.get("files", []):
        print("  {}".format(path))
    return 0


def cmd_local_doctor(args, settings):
    print("Local analysis tools (all optional, none upload anything)\n")
    missing = []
    for key, binary, found, install in local_tools.status():
        print("  {:<9} {}".format(key, found or "MISSING"))
        if not found:
            missing.append((binary, install))
    device = local_tools.detect_device()
    print("\n  device    {}".format(device or "default (no Apple Silicon MPS)"))
    if missing:
        print("\nTo install what's missing:")
        for binary, install in missing:
            print("  {:<9} {}".format(binary, install))
    return 0


def cmd_local_stems(args, settings):
    return _emit(
        local_tools.stems(
            args.input,
            args.output,
            model=args.model,
            device=args.device or local_tools.detect_device(),
            two_stems=args.two_stems,
            dry_run=args.dry_run,
        )
    )


def cmd_local_structure(args, settings):
    result = local_tools.structure(args.input, args.output, dry_run=args.dry_run)
    _emit(result)
    if not args.dry_run:
        for path in result["files"]:
            print()
            _print_json(local_tools.summarize_structure(path))
    return 0


def cmd_local_lyrics(args, settings):
    return _emit(
        local_tools.lyrics(
            args.input,
            args.output,
            model=args.model,
            language=args.language,
            dry_run=args.dry_run,
        )
    )


# -- music.ai -------------------------------------------------------------


def _music_ai_client(settings):
    key = settings.require("MUSIC_AI_API_KEY", service="Music.AI")
    return music_ai_adapter.MusicAIClient(key)


def cmd_music_ai_application(args, settings):
    _print_json(_music_ai_client(settings).application())
    return 0


def cmd_music_ai_workflows(args, settings):
    items = _music_ai_client(settings).workflows(contains=args.contains)
    if not items:
        print("No workflows matched. Run without --contains to see them all.")
        return 0
    for item in items:
        print("{:<40} {}".format(item.get("slug", "?"), item.get("name", "")))
    return 0


def cmd_music_ai_job(args, settings):
    _print_json(_music_ai_client(settings).get_job(args.job_id))
    return 0


def cmd_music_ai_process(args, settings):
    client = _music_ai_client(settings)
    result = client.process(
        path=args.input,
        workflow=args.workflow,
        dest_dir=args.output,
        name=args.name,
        timeout=settings.poll_timeout(),
    )
    for name, path in sorted(result["files"].items()):
        print("{:<24} {}".format(name, path))
    _maybe_record(args, settings, "music-ai", args.workflow, result["job"].get("id"))
    if args.delete_remote:
        client.delete_job(result["job"]["id"])
        print("Deleted remote job {}".format(result["job"]["id"]))
    return 0


# -- kits -----------------------------------------------------------------


def _kits_client(settings):
    key = settings.require("KITS_API_KEY", service="Kits")
    interval = settings.get("KITS_MIN_POST_INTERVAL")
    kwargs = {}
    if interval is not None:
        try:
            kwargs["min_post_interval"] = int(interval)
        except ValueError:
            pass
    return kits_adapter.KitsClient(key, **kwargs)


def cmd_kits_models(args, settings):
    models = _kits_client(settings).voice_models()
    if not models:
        print("No voice models on this account yet.")
        return 0
    for model in models:
        print("{:<14} {}".format(model.get("id", "?"), model.get("name", "")))
    return 0


def cmd_kits_vocals(args, settings):
    result = _kits_client(settings).separate_vocals(
        path=args.input, dest_dir=args.output, timeout=settings.poll_timeout()
    )
    for name, path in sorted(result["files"].items()):
        print("{:<24} {}".format(name, path))
    _maybe_record(args, settings, "kits", "vocal-separation", result["job"].get("id"))
    return 0


def cmd_kits_stems(args, settings):
    result = _kits_client(settings).split_stems(
        path=args.input, dest_dir=args.output, timeout=settings.poll_timeout()
    )
    for name, path in sorted(result["files"].items()):
        print("{:<24} {}".format(name, path))
    _maybe_record(args, settings, "kits", "stem-split", result["job"].get("id"))
    return 0


def cmd_kits_convert(args, settings):
    result = _kits_client(settings).convert_voice(
        path=args.input,
        voice_model_id=args.voice_model,
        dest_dir=args.output,
        timeout=settings.poll_timeout(),
    )
    for name, path in sorted(result["files"].items()):
        print("{:<24} {}".format(name, path))
    _maybe_record(args, settings, "kits", "voice-conversion", result["job"].get("id"))
    return 0


# -- moises ---------------------------------------------------------------


def _moises_client(settings):
    key = settings.require("MOISES_API_KEY", service="Moises")
    scheme = settings.get("MOISES_AUTH_SCHEME", "raw")
    return moises_adapter.MoisesClient(key, auth_scheme=scheme)


def cmd_moises_auth(args, settings):
    """Find out which auth scheme the server accepts, empirically."""
    client = _moises_client(settings)
    scheme = client.detect_auth_scheme()
    print("Moises accepted the key using the {!r} scheme.".format(scheme))
    if scheme != "raw":
        print("Pin it by adding to .env:\n  MOISES_AUTH_SCHEME={}".format(scheme))
    return 0


def cmd_moises_introspect(args, settings):
    """Print the live GraphQL schema so real queries can be written from it."""
    client = _moises_client(settings)
    if args.detect_auth:
        client.detect_auth_scheme()
    schema = client.introspect()
    if args.json:
        _print_json(schema)
    else:
        print(moises_adapter.format_schema(schema, contains=args.contains))
    return 0


def cmd_moises_query(args, settings):
    """Run an arbitrary GraphQL operation — the escape hatch until the
    schema-specific commands exist."""
    query = args.query
    if query == "-":
        query = sys.stdin.read()
    variables = json.loads(args.variables) if args.variables else None
    _print_json(_moises_client(settings).execute(query, variables))
    return 0


# -- suno -----------------------------------------------------------------


def cmd_suno_status(args, settings):
    state = suno_adapter.status(settings)
    print("suno: {}".format(state["status"]))
    print(state["detail"])
    return 0 if state["status"] == suno_adapter.STATUS_READY else 1


# -- shared ---------------------------------------------------------------


def _maybe_record(args, settings, service, workflow, job_id):
    """Append a job record to the owning project, if the output is inside one."""
    if not job_id:
        return
    out = Path(args.output).resolve()
    root = settings.projects_dir.resolve()
    try:
        relative = out.relative_to(root)
    except ValueError:
        return
    project_dir = root / relative.parts[0]
    if not (project_dir / projects.METADATA_FILE).exists():
        return
    from datetime import datetime, timezone

    projects.record_job(
        project_dir,
        {
            "service": service,
            "workflow": workflow,
            "job_id": job_id,
            "output": str(out),
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="music-stack",
        description="A programmable songwriting pipeline over Music.AI, Kits, and ffmpeg.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check local tools and credentials").set_defaults(
        func=cmd_doctor
    )

    ana = sub.add_parser(
        "analyze",
        help="ONE COMMAND: normalize, structure, stems, lyrics, and a brief",
    )
    ana.add_argument("--input", required=True, help="any audio or video file")
    ana.add_argument("--title", help="song title (defaults to the filename)")
    ana.add_argument(
        "--skip",
        action="append",
        choices=["normalize", "structure", "stems", "lyrics"],
        help="skip a stage; repeatable",
    )
    ana.add_argument("--dry-run", action="store_true", help="plan only, run nothing")
    ana.set_defaults(func=cmd_analyze)

    project = sub.add_parser("project", help="song project directories")
    project_sub = project.add_subparsers(dest="subcommand", required=True)
    new = project_sub.add_parser("new", help="create a project tree")
    new.add_argument("title")
    new.add_argument("--exist-ok", action="store_true", help="fill in missing subdirs")
    new.set_defaults(func=cmd_project_new)
    project_sub.add_parser("list", help="list projects").set_defaults(
        func=cmd_project_list
    )

    aud = sub.add_parser("audio", help="local ffmpeg operations")
    audio_sub = aud.add_subparsers(dest="subcommand", required=True)
    norm = audio_sub.add_parser("normalize", help="lossless WAV working copy")
    norm.add_argument("src")
    norm.add_argument("dest")
    norm.add_argument("--rate", type=int, default=audio.TARGET_RATE)
    norm.add_argument("--bit-depth", type=int, default=audio.TARGET_BITS)
    norm.add_argument("--overwrite", action="store_true")
    norm.set_defaults(func=cmd_audio_normalize)
    insp = audio_sub.add_parser("inspect", help="ffprobe summary")
    insp.add_argument("path")
    insp.add_argument("--full", action="store_true", help="full ffprobe JSON")
    insp.set_defaults(func=cmd_audio_inspect)

    loc = sub.add_parser(
        "local", help="local analysis — no account, nothing uploaded"
    )
    loc_sub = loc.add_subparsers(dest="subcommand", required=True)
    loc_sub.add_parser("doctor", help="which local tools are installed").set_defaults(
        func=cmd_local_doctor
    )
    st = loc_sub.add_parser("stems", help="separate stems with Demucs")
    st.add_argument("--input", required=True)
    st.add_argument("--output", required=True)
    st.add_argument("--model", default=local_tools.DEFAULT_DEMUCS_MODEL)
    st.add_argument("--device", help="e.g. mps on Apple Silicon (auto-detected)")
    st.add_argument("--two-stems", help="isolate one source, e.g. vocals")
    st.add_argument("--dry-run", action="store_true", help="print the command only")
    st.set_defaults(func=cmd_local_stems)

    stru = loc_sub.add_parser(
        "structure", help="tempo, beats, and labelled sections with allin1"
    )
    stru.add_argument("--input", required=True)
    stru.add_argument("--output", required=True)
    stru.add_argument("--dry-run", action="store_true")
    stru.set_defaults(func=cmd_local_structure)

    lyr = loc_sub.add_parser("lyrics", help="transcribe with Whisper")
    lyr.add_argument("--input", required=True)
    lyr.add_argument("--output", required=True)
    lyr.add_argument("--model", default="small")
    lyr.add_argument("--language")
    lyr.add_argument("--dry-run", action="store_true")
    lyr.set_defaults(func=cmd_local_lyrics)

    mai = sub.add_parser("music-ai", help="Music.AI workflows")
    mai_sub = mai.add_subparsers(dest="subcommand", required=True)
    mai_sub.add_parser("application", help="account + workflow list").set_defaults(
        func=cmd_music_ai_application
    )
    wf = mai_sub.add_parser("workflows", help="list workflows (free, no credits)")
    wf.add_argument("--contains", help="filter by substring")
    wf.set_defaults(func=cmd_music_ai_workflows)
    job = mai_sub.add_parser("job", help="fetch one job by id")
    job.add_argument("job_id")
    job.set_defaults(func=cmd_music_ai_job)
    proc = mai_sub.add_parser("process", help="upload, run a workflow, download results")
    proc.add_argument("--workflow", required=True)
    proc.add_argument("--input", required=True)
    proc.add_argument("--output", required=True)
    proc.add_argument("--name")
    proc.add_argument(
        "--delete-remote",
        action="store_true",
        help="delete the job and its stored outputs after downloading",
    )
    proc.set_defaults(func=cmd_music_ai_process)

    kit = sub.add_parser("kits", help="Kits AI voice tools")
    kits_sub = kit.add_subparsers(dest="subcommand", required=True)
    kits_sub.add_parser("models", help="list voice models").set_defaults(
        func=cmd_kits_models
    )
    for name, handler, extra in (
        ("vocals", cmd_kits_vocals, None),
        ("stems", cmd_kits_stems, None),
        ("convert", cmd_kits_convert, "voice-model"),
    ):
        node = kits_sub.add_parser(name)
        node.add_argument("--input", required=True)
        node.add_argument("--output", required=True)
        if extra:
            node.add_argument("--voice-model", required=True)
        node.set_defaults(func=handler)

    moi = sub.add_parser("moises", help="Moises GraphQL API (self-serve door)")
    moi_sub = moi.add_subparsers(dest="subcommand", required=True)
    moi_sub.add_parser(
        "auth", help="detect which auth scheme your key uses"
    ).set_defaults(func=cmd_moises_auth)
    intro = moi_sub.add_parser(
        "introspect", help="dump the live GraphQL schema (no guessing)"
    )
    intro.add_argument("--contains", help="filter operations by substring")
    intro.add_argument("--json", action="store_true", help="raw JSON instead of text")
    intro.add_argument(
        "--detect-auth",
        action="store_true",
        help="try both auth schemes first",
    )
    intro.set_defaults(func=cmd_moises_introspect)
    q = moi_sub.add_parser("query", help="run a raw GraphQL operation ('-' for stdin)")
    q.add_argument("query")
    q.add_argument("--variables", help="JSON object of variables")
    q.set_defaults(func=cmd_moises_query)

    suno = sub.add_parser("suno", help="Suno (disabled until configured)")
    suno_sub = suno.add_subparsers(dest="subcommand", required=True)
    suno_sub.add_parser("status").set_defaults(func=cmd_suno_status)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        return args.func(args, settings)
    except MusicStackError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
