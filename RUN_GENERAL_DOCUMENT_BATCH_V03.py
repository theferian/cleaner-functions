"""Batch adapter: existing V06 logic, deferred reporting review, no automatic approvals."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_runner():
    spec = importlib.util.spec_from_file_location('general_document_v06', ROOT/'RUN_GENERAL_DOCUMENT_V06.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def execute(m, args):
    m.COLOR_MODE = args.color
    m.EVENT_LOG = None
    book = Path(args.workbook).resolve()
    progress = dict(project=args.project, status_date=args.status_date, workbook=str(book), status='RUNNING', review_items=[])
    run_dir = None
    def persist():
        m.save_progress(run_dir, progress)
    def defer(exc):
        progress['review_items'].append(dict(stage=exc.stage, reason=str(exc), count=exc.count))
        progress.update(status='REVIEW_REQUIRED', pause_stage=exc.stage)
        persist()
    try:
        rid, run_dir = m.choose_run(args, book, progress)
        progress['run_id'] = rid
        m.EVENT_LOG = run_dir/'general_doc_console.log'
        # Structural gates remain dependencies: never invent mappings to get counts.
        for stage in m.STAGES:
            m.guarded_stage(args, rid, run_dir, book, stage)
            progress['last_stage'] = stage
            persist()
        m.guard_wrong_field_replacement(run_dir)
        try:
            board = m.guarded_board_to_log(args, run_dir)
        except m.ReviewNeeded as exc:
            defer(exc)
            # Reporting can use extracted records, while their issues remain open.
            board = m.load(run_dir/m.LOG_NAME)
        progress['last_stage'] = 'BOARD_TO_LOG'
        persist()
        try:
            m.guarded_coverage(args, run_dir)
        except m.ReviewNeeded as exc:
            defer(exc)
        progress['last_stage'] = 'COVERAGE'
        persist()
        try:
            report = m.guarded_engineering(args, run_dir)
        except m.ReviewNeeded as exc:
            defer(exc)
            report = m.load(run_dir/'engineering_lists'/m.ENGINEERING_NAME)
        progress['last_stage'] = 'ENGINEERING'
        if progress['review_items']:
            progress.update(status='REVIEW_REQUIRED', report_status='PROVISIONAL_REVIEW_PENDING', note='; '.join(x['stage']+': '+x['reason'] for x in progress['review_items']))
        else:
            progress.update(status='COMPLETE_WITH_REVIEWED_EXCEPTIONS' if board.get('issues') or report.get('diagnostics') else 'COMPLETE', report_status='CALCULATED', pause_stage='')
        persist()
        return 2 if progress['review_items'] else 0
    except m.ReviewNeeded as exc:
        defer(exc)
        progress.update(note=str(exc), report_status='BLOCKED_STRUCTURAL_REVIEW')
        persist()
        return 2
    except Exception as exc:
        progress.update(status='ERROR', error=str(exc))
        persist()
        return 1

def main():
    m = load_runner()
    args = m.parse_args()
    # Explicit operator review retains V06's interactive correction workflow.
    if not args.non_interactive:
        return m.main()
    return execute(m, args)

if __name__ == '__main__':
    raise SystemExit(main())
