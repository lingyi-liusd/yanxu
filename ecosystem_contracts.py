"""Unified distribution and version handshake. Contains no user or path identifiers."""
import hashlib
from pathlib import Path

VERSION='yanxu.ecosystem.v2'
FILES=('server.py','ecosystem.py','group_chat.py','review_service.py','review_context.py','review_history.py','observation_service.py','result_observation.py','source_extractors.py','lineage_service.py','extension_contracts.py','radar_fetch.py',
       'ecosystem_contracts.py','agent_connection.py','agent_gateway.py','project_backup.py','mcp-server.js',
       'index.html','ecosystem.js','ecosystem_state.js','ecosystem_client.js','review_ui.js','chat_ui.js','ecosystem.css','apps/shell.html','apps/shell.js','apps/shell.css')


def build_id(root=None):
    root=Path(root or Path(__file__).resolve().parent)
    digest=hashlib.sha256()
    for name in FILES:
        digest.update(name.encode());digest.update(b'\0');digest.update((root/name).read_bytes());digest.update(b'\0')
    return digest.hexdigest()


def capabilities():
    return {'product':'yanxu','distribution':'unified','version':VERSION,
            'contracts':{'ecosystem':2,'review_brief':1,'source_extractor':1,'external_reply':1},
            'features':['radar.group_push.v1','group.chat.v1','observe.result_proposals.v1','review.history_snapshot.v1','adoption.target_project_version.v1','review.context_selection.v1','review.materials','review.citations','review.human_edits','observe.coverage','observe.structured_feed','source_pack.import',
                        'decision.needs_review','review.export','revision.object','usage.restore_floor'],
            'modes':{'project':'/','chat':'/?mode=chat','review':'/?mode=review','observe':'/?mode=observe'},
            'focus_views':{'review':'/apps/discussion/','observe':'/apps/radar/'}}
