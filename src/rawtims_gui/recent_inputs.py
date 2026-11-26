"""Recent completed input files and selected directories; no automatic reopening."""
import json
from pathlib import Path

LIMIT = 8


def recent(settings, kind):
    try:
        values = json.loads(settings.value('inputs/recent-'+kind,'[]',type=str))
        if not isinstance(values,list):
            return []
        valid = Path.is_file if kind == 'files' else Path.is_dir
        return list(dict.fromkeys(p for p in values if isinstance(p,str) and valid(Path(p))))[:LIMIT]
    except (ValueError,TypeError,OSError):
        return []


def remember(settings, kind, path):
    path = str(Path(path).resolve())
    settings.setValue('inputs/recent-'+kind,json.dumps([path,*[p for p in recent(settings,kind) if p != path]][:LIMIT]))


def populate(window, parent):
    for label,kind in [('Run files','files'),('Folders','folders')]:
        menu = parent.addMenu(label)
        paths = recent(window.settings,kind)
        for path in paths:
            action = menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(lambda _c=False,p=path: window.open_paths([p]))
        if not paths:
            menu.addAction('No recent '+label.lower()).setEnabled(False)
        menu.addSeparator()
        clear = menu.addAction('Clear list')
        clear.setEnabled(bool(paths))
        clear.triggered.connect(lambda _c=False,k=kind: window.settings.remove('inputs/recent-'+k))
