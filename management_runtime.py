"""Bounded local management executor; never writes scientific records or source files."""
import hashlib
import json
import os
import pathlib
import stat
import re
import platform_support


def validate_analysis(snapshot, analysis, read_receipt=None):
    """Narrow factual cross-check; no claim of general model correctness."""
    notes = []
    if 'file_observations' in snapshot and analysis:
        count = len(snapshot['file_observations'])
        for claimed in set(re.findall(r'(\d+)\s*个文件', str(analysis.get('changes','')))):
            if int(claimed) != count:
                notes.append('模型提及'+claimed+'个观察文件，但调用输入实际为'+str(count)+'个；此数值需复核，以版本绑定的输入列表为准。')
    if analysis and read_receipt and read_receipt.get('state')=='current_ledger':
        counts=read_receipt.get('counts') or {}
        text='\n'.join(str(value) for value in analysis.values())
        # Deliberately narrow: only explicit current file/source counts, not
        # historic counts, tasks, estimates, or general model correctness.
        for field,label in (('pending','待处理'),('processed','已处理')):
            patterns=(r'当前\s*'+label+r'(?:的)?(?:资料|文件)\s*[：:]?\s*(\d+)\s*[项个份]',
                r'当前(?:有)?\s*(\d+)\s*[项个份](?:资料|文件)\s*'+label)
            for claimed in {number for pattern in patterns for number in re.findall(pattern,text)}:
                if counts.get(field) is not None and int(claimed)!=counts[field]:
                    notes.append('摘要称当前'+label+'资料'+claimed+'项，但调用时处理账本为'+str(counts[field])+'项；以阅读回执为准，不能用历史批次统计替代。')
    return notes


def observe(snapshot, workspace):
    """Only registered absolute files below the consented workspace, no directory crawl.

    Hashing reads local bytes but only metadata is returned/sent to the model.
    Symlinks, special files, secret-like names and oversized files are not opened.
    """
    root = pathlib.Path(workspace)
    refs = {}
    for row in snapshot.get('artifacts', []) + snapshot.get('files', []):
        path = row.get('reference') or row.get('path')
        if not isinstance(path, str) or not pathlib.Path(path).is_absolute():
            continue
        candidate = pathlib.Path(os.path.abspath(path))
        if not candidate.is_relative_to(root):
            continue
        refs.setdefault(str(candidate), set()).add(row.get('source_version') or row.get('content_hash') or row.get('hash') or '')
    if len(refs) > 256:
        raise ValueError('登记文件超过256个，停止观察；请缩小范围')
    observations = []
    for name, versions in sorted(refs.items()):
        path = pathlib.Path(name)
        item = {'path': name, 'registered_versions': sorted(versions)}
        parts = path.relative_to(root).parts
        if any(p.startswith('.') or any(s in p.lower() for s in ('token', 'credential', 'secret', 'password')) for p in parts):
            item['state'] = 'excluded'
            observations.append(item)
            continue
        # Open through directory descriptors: no symlink races or escape via a parent.
        descriptors = []
        try:
            if os.name == 'nt':
                raw = platform_support.windows_read(path, root, 2 * 1024 * 1024)
                version = 'sha256:' + hashlib.sha256(raw).hexdigest()
                item.update(state='present', size=len(raw), observed_version=version,
                            matches_registered=version in versions or version[7:] in versions)
                observations.append(item)
                continue
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(fd)
            for part in parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                descriptors.append(fd)
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            descriptors.append(file_fd)
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                item['state'] = 'excluded'
            elif before.st_size > 2 * 1024 * 1024:
                item.update(state='oversize', size=before.st_size, mtime_ns=before.st_mtime_ns)
            else:
                digest = hashlib.sha256()
                total = 0
                while total <= 2 * 1024 * 1024:
                    chunk = os.read(file_fd, 65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                after = os.fstat(file_fd)
                if total > 2 * 1024 * 1024 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    item['state'] = 'unstable'
                else:
                    version = 'sha256:' + digest.hexdigest()
                    item.update(state='present', size=after.st_size, observed_version=version,
                                matches_registered=version in versions or version[7:] in versions)
        except FileNotFoundError:
            item['state'] = 'missing'
        except ValueError:
            item['state'] = 'oversize_or_unstable'
        except OSError:
            item['state'] = 'inaccessible_or_symlink'
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        observations.append(item)
    return observations


def audit(snapshot):
    """Deterministic checks, not a scientific review and not a second model call."""
    findings = []
    for file in snapshot.get('file_observations', []):
        if file['state'] != 'present' or not file.get('matches_registered'):
            findings.append({'kind': 'source_version', 'source': file['path'],
                             'detail': file, 'status': 'NEEDS_REVIEW'})
    for result in snapshot.get('results', []):
        if not result.get('source_ref') or not result.get('source_version'):
            findings.append({'kind': 'missing_source', 'source': result.get('id'), 'status': 'UNKNOWN'})
    active = [a for a in snapshot.get('actions', []) if a.get('status') in ('claimed', 'running')]
    completed = [a for a in snapshot.get('actions', []) if a.get('status') == 'finished']
    return {'executor': 'local-registered-record-review-v1', 'delivery_status': 'COMPLETE',
            'scientific_status': 'NOT_ASSESSED', 'verification_status': 'UNVERIFIED',
            'outcome': 'NEEDS_REVIEW' if findings else 'NO_RULE_FINDING', 'findings': findings,
            'active_action_ids': [a['id'] for a in active],
            'completed_action_ids': [a['id'] for a in completed],
            'boundary': '核查只报告记录与版本，不修改任务/原文件，不验证科学结论；任务未完成与某阶段Action完成不自动构成矛盾。'}
