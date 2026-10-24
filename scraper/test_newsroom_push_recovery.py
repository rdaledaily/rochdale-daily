"""A concurrent editor update must survive a failed scraper push."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PushRecovery(unittest.TestCase):
    def test_push_race_merges_stories_and_renders_only_during_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, local, editor = [root / name for name in ('remote.git', 'local', 'editor')]
            def git(*args, cwd=None):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.STDOUT, text=True)
            git('init', '--bare', str(remote))
            git('clone', str(remote), str(local))
            git('checkout', '-b', 'main', cwd=local)
            for name in ('user.name', 'user.email'):
                git('config', name, 'test' if name.endswith('name') else 'test@example.org', cwd=local)
            script = (ROOT / 'scraper/publish_newsroom_snapshot.sh').read_text()
            # Populate every staged path so missing optional fixture files do
            # not obscure the push-race behavior under test.
            import re
            stage = script.split('stage_newsroom() {', 1)[1].split('finalise_cards_policy()', 1)[0]
            # The staging list is a bash array since 24 Oct 2026 (only paths
            # that exist are added).
            paths = re.search(r'local paths=\((.*?)\)', stage, re.S).group(1).split()
            for name in paths:
                path = local / name
                if name in {'manual_articles.d','assets/img/cards','articles','wards/','news/'}:
                    path.mkdir(parents=True, exist_ok=True)
                    (path / '.keep').write_text('fixture')
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('[]' if name.endswith('.json') else 'fixture')
            (local / 'scraper').mkdir(exist_ok=True)
            (local / 'scraper/publish_newsroom_snapshot.sh').write_text(script)
            (local / 'story_blocklist.json').write_text('{}')
            git('add', '.', cwd=local)
            git('commit', '-m', 'base', cwd=local)
            git('push', '-u', 'origin', 'main', cwd=local)
            git('clone', '--branch', 'main', str(remote), str(editor))
            git('config', 'user.name', 'editor', cwd=editor)
            git('config', 'user.email', 'editor@example.org', cwd=editor)
            existing = {'id':'editor-story','slug':'editor-story','title':'Queen’s Drive homes approved',
                        'content_html':'<p>New homes in Kirkholt.</p>', 'editorial_lock':True,
                        'source_url':'https://example.org/editor', 'published_at':'2026-10-14T10:00:00Z'}
            (editor / 'articles.json').write_text(json.dumps([existing]))
            git('add', 'articles.json', cwd=editor)
            git('commit', '-m', 'concurrent editor story', cwd=editor)
            git('push', 'origin', 'main', cwd=editor)
            incoming = {'id':'scraper-story','slug':'scraper-story','title':'Littleborough cricket club wins match',
                        'content_html':'<p>Local cricket match report.</p>',
                        'source_url':'https://example.org/scraper', 'published_at':'2026-10-14T11:00:00Z'}
            (local / 'articles.json').write_text(json.dumps([incoming]))
            binary = root / 'bin'; binary.mkdir()
            calls = root / 'calls.jsonl'
            shim = binary / 'python'
            shim.write_text('#!' + sys.executable + '\n' +
                'import json,os,subprocess,sys\n' +
                'with open(os.environ["CALLS"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n' +
                'if sys.argv[1:2]==["scraper/merge_feeds.py"]:\n' +
                ' sys.exit(subprocess.call([sys.executable,os.environ["MERGER"],*sys.argv[2:]]))\n')
            shim.chmod(0o755)
            env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],
                 'CALLS':str(calls),'MERGER':str(ROOT/'scraper/merge_feeds.py'),
                 'GITHUB_REF_NAME':'main','GITHUB_OUTPUT':str(root/'output')}
            result=subprocess.run(['bash','scraper/publish_newsroom_snapshot.sh'],cwd=local,env=env,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            published=json.loads(git('--git-dir',str(remote),'show','main:articles.json'))
            self.assertEqual({r['slug'] for r in published},{'editor-story','scraper-story'})
            self.assertTrue(next(r for r in published if r['slug']=='editor-story')['editorial_lock'])
            commands=[json.loads(line) for line in calls.read_text().splitlines()]
            renders=[c for c in commands if any('render_main' in arg or 'generate_newspaper_pages.py' in arg for arg in c)]
            self.assertEqual(len(renders),1,commands)
            self.assertIn('published=true',(root/'output').read_text())


if __name__ == '__main__':
    unittest.main()
