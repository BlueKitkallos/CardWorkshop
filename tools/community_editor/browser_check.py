#!/usr/bin/env python3
"""Local browser workflow checks. Requires Chrome and Python websockets; no emulator."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

import websockets


async def check(args):
    processes = []
    try:
        server = subprocess.Popen([sys.executable, 'tools/pack_editor.py', '--no-browser', '--port', '0',
                                   '--rom', str(args.rom)], stdout=subprocess.PIPE, text=True)
        processes.append(server)
        url = server.stdout.readline().strip().split()[-1]
        with tempfile.TemporaryDirectory(prefix='card-workshop-browser-', ignore_cleanup_errors=True) as profile:
            chrome = subprocess.Popen([args.chrome, '--headless=new', '--no-sandbox', '--disable-dev-shm-usage',
                                       '--disable-gpu', '--remote-debugging-port=0', f'--user-data-dir={profile}', url],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(chrome)
            downloads = Path(profile) / 'downloads'
            downloads.mkdir()
            port_file = Path(profile) / 'DevToolsActivePort'
            for _ in range(100):
                if port_file.exists():
                    break
                await asyncio.sleep(.1)
            port = port_file.read_text().splitlines()[0]
            targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list'))
            target = next(t for t in targets if t['type'] == 'page')
            async with websockets.connect(target['webSocketDebuggerUrl'], max_size=20*1024*1024) as socket:
                serial = 0
                errors = []

                async def command(method, params=None):
                    nonlocal serial
                    serial += 1
                    ident = serial
                    await socket.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
                    while True:
                        message = json.loads(await socket.recv())
                        if message.get('method') == 'Runtime.exceptionThrown':
                            errors.append(message['params'])
                        if message.get('id') == ident:
                            if 'error' in message:
                                raise RuntimeError(message['error'])
                            return message.get('result', {})

                async def js(code):
                    result = await command('Runtime.evaluate', {'expression': code, 'awaitPromise': True,
                                                               'returnByValue': True})
                    if 'exceptionDetails' in result:
                        raise AssertionError(result['exceptionDetails'])
                    return result.get('result', {}).get('value')

                async def verify(code, label):
                    if not await js(code):
                        raise AssertionError(label)
                    print('PASS:', label, flush=True)

                await command('Runtime.enable')
                await command('Page.enable')
                await asyncio.sleep(.5)
                await command('Emulation.setDeviceMetricsOverride', {'width': 1500, 'height': 1050,
                                                                      'deviceScaleFactor': 1, 'mobile': False})
                await js("new Promise((done,fail)=>{let n=0;const t=setInterval(()=>{if(typeof project!=='undefined'&&project&&cpuMetadata){clearInterval(t);done(true);}else if(++n>300){clearInterval(t);fail('Editor did not load');}},100);})")
                await verify("project.packs.length===81&&!$('#saveProject').disabled", 'clean ROM and actions loaded')
                await verify("[...document.querySelectorAll('.rarity textarea')].every(x=>x.hidden)", 'images are the default list view')
                await js("document.querySelector('[aria-label=\"Toggle common text list\"]').click()")
                await verify("!document.querySelector('[aria-label=\"common card list\"]').hidden", 'text view is available')
                await js("(()=>{const t=document.querySelector('[aria-label=\"common card list\"]');t.value+='\\nFuture Community Card';t.dispatchEvent(new Event('change'));})()")
                await verify("current().cards.common.includes('Future Community Card')&&!$('#undo').disabled", 'draft cards stay editable')
                await js("$('#undo').click()")
                await verify("!current().cards.common.includes('Future Community Card')&&!$('#redo').disabled", 'Undo restores card lists')
                await js("$('#redo').click()")
                await verify("current().cards.common.includes('Future Community Card')", 'Redo restores the edit')
                await js("$('#export').onclick()")
                await verify("$('#issues').open&&$('#issueList').textContent.includes('Future Community Card')&&!busy", 'export checks drafts before building')
                await js("document.querySelector('#issueList button').click()")
                await verify("!$('#issues').open&&tab==='packs'&&selected===1", 'issues open the affected editor')
                await js("$('#undo').click();$('#add').click()")
                await verify("current().id===97&&$('#editor').textContent.includes('4 Commons')", 'new pack shows required contents')
                await js("document.querySelector('[aria-label=\"Add card to rare\"]').click();document.querySelector('dialog[open] input').value='Dark Hole';document.querySelector('dialog[open] input').dispatchEvent(new Event('input'));document.querySelector('dialog[open] .picker-card').click()")
                await verify("current().cards.rare.includes(resolve('Dark Hole').ref)&&document.querySelector('dialog[open] .picker-card').disabled", 'pack Add card picker adds once and prevents duplicates')
                await js("document.querySelector('dialog[open]').close()")
                await js("cardInfo('id:4007');[...document.querySelectorAll('#cardInfo button')].find(b=>b.textContent==='Add to pack').click()")
                await verify("current().cards.common.includes('id:4007')", 'click to add cards to packs')
                await js("(()=>{const p=current(),transfer=new DataTransfer();transfer.setData('application/x-wc-card',JSON.stringify({ref:'id:4007',tab,selected,section:'common',index:0}));document.querySelector('[data-rarity=ultra]').dispatchEvent(new DragEvent('drop',{dataTransfer:transfer,bubbles:true,cancelable:true}));})()")
                await verify("current().cards.ultra.includes('id:4007')&&!current().cards.common.length", 'drag changes pack rarity without duplicating')
                await js("setTab('decks');$('#add').click();current().main=[];current().extra=[];current().side=[];changed();editor();cardInfo('id:4007');[...document.querySelectorAll('#cardInfo button')].find(b=>b.textContent==='Add to deck').click()")
                await js("document.querySelector('[aria-label=\"Add card to extra\"]').click();document.querySelector('dialog[open] input').value='Dark Hole';document.querySelector('dialog[open] input').dispatchEvent(new Event('input'))")
                await verify("!document.querySelector('dialog[open] .picker-card')", 'Extra Deck picker excludes Spells')
                await js("document.querySelector('dialog[open] input').value='Stardust Dragon';document.querySelector('dialog[open] input').dispatchEvent(new Event('input'));document.querySelector('dialog[open] .picker-card').click()")
                await verify("current().extra.includes(resolve('Stardust Dragon').ref)", 'deck Add card picker adds to the chosen section')
                await js("document.querySelector('dialog[open]').close();$('#undo').click()")
                await verify("current().main.length===1&&current().main[0]==='id:4007'", 'click to add deck cards')
                await js("document.querySelector('.copy-controls button:last-child').click();document.querySelector('.copy-controls button:last-child').click();document.querySelector('.copy-controls button:last-child').click()")
                await verify("current().main.length===3&&document.querySelectorAll('[data-rarity=main] .tile').length===1", 'copies grouped and capped at three')
                await js("cardInfo(resolve('Dark Hole').ref);document.querySelector('[aria-label=\"Add to deck section\"]').value='extra';[...document.querySelectorAll('#cardInfo button')].find(b=>b.textContent==='Add to deck').click()")
                await verify("current().extra.length===0", 'Spells cannot enter Extra Deck')
                await js("(()=>{const extra=catalog.filter(c=>c.placement==='extra'&&c.id===c.canonical_id).slice(0,6);current().extra=extra.slice(0,5).flatMap(c=>[c.ref,c.ref,c.ref]);changed();editor();cardInfo(extra[5].ref);[...document.querySelectorAll('#cardInfo button')].find(b=>b.textContent==='Add to deck').click();})()")
                await verify("current().extra.length===15", 'Extra Deck capped at 15')
                await js("$('#listSearch').value='copy';list();const file=selected;setTab('packs');setTab('decks')")
                await verify("$('#listSearch').value==='copy'&&current().file.startsWith('user_')", 'tab selection and search remembered')
                await js("setTab('opponents');$('#add').click();[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent==='CPU Duel').click()")
                await verify("current().deck.startsWith('user_')", 'new CPUs get independent decks')
                await js("[...document.querySelectorAll('#editor button')].find(b=>b.textContent==='Change key card').click()")
                await verify("document.querySelector('dialog[open] [aria-label=\"Key card source\"]').value==='deck'", 'key-card picker starts with the CPU deck')
                await js("document.querySelector('dialog[open] .picker-card').click()")
                await verify("!!resolve(current().key_card)", 'key-card selection updates the CPU')
                await js("[...document.querySelectorAll('#editor button')].find(b=>b.textContent==='Copy base game CPU').click();document.querySelector('dialog[open] input').value='Akiza';document.querySelector('dialog[open] input').dispatchEvent(new Event('input'));document.querySelector('dialog[open] .picker-card').click()")
                await verify("current().portrait===129&&current().name==='Akiza Izinski'", 'named CPU templates copy correctly')
                await js("$('#listSearch').value='Moja';list();document.querySelector('#list .list-row').click()")
                await verify("selected==='base:301'&&current().name==='Moja'&&document.querySelectorAll('#list .list-row img').length===1", 'base game CPUs are listed with portraits and searchable')
                await js("(()=>{const field=[...document.querySelectorAll('#editor label')].find(x=>x.textContent==='Name');const input=document.getElementById(field.htmlFor);input.value='Workshop Moja';input.dispatchEvent(new Event('change'));})()")
                await verify("JSON.stringify(project.base_cpus[301])==='{\"name\":\"Workshop Moja\"}'", 'a base game CPU keeps only its changed name')
                await verify("fetch('/api/project').then(r=>r.json()).then(d=>api('/api/validate',{...d.project,base_cpus:project.base_cpus})).then(r=>r.json()).then(d=>d.issues.length===0)", 'a renamed base game CPU exports with no issues')
                await js("[...document.querySelectorAll('#editor button')].find(b=>b.textContent==='Reset to base game').click()")
                await verify("!project.base_cpus[301]&&current().name==='Moja'", 'Reset to base game drops the changes')
                await verify("[...document.querySelectorAll('#list .list-heading')].map(h=>h.textContent).join()==='CPU Duel'", 'search keeps only the matching section')
                await js("(()=>{document.querySelector('#editor .cpu-settings').open=true;document.querySelector('#editor .cpu-dialogue').open=true;const box=[...document.querySelectorAll('#editor .cpu-dialogue textarea')];box[2].value='Workshop draw line';box[2].dispatchEvent(new Event('change'));})()")
                await verify("(()=>{const box=[...document.querySelectorAll('#editor .cpu-dialogue textarea')];return box.length===28&&box[0].value===baseCpu(301).talk[0]&&box[0].value.length>0&&JSON.stringify(project.base_cpus[301])==='{\"talk\":{\"2\":\"Workshop draw line\"}}';})()", 'base game dialogue is prefilled and only the changed line is stored')
                await js("[...document.querySelectorAll('#editor button')].find(b=>b.textContent==='Use base game dialogue').click()")
                await verify("!project.base_cpus[301]", 'Use base game dialogue restores the lines')
                await js("$('#listSearch').value='';list()")
                await verify("[...document.querySelectorAll('#list .list-heading')].map(h=>h.textContent).join()==='CPU Duel,CPU Turbo Duel,CPU Tag Duel,CPU Tag Turbo Duel'", 'the four rosters have their own sections')
                await js("$('#add').click();[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent==='CPU Tag Duel').click()")
                await verify("current().tag&&!current().turbo&&baseCpu(current().partner).list==='tag'&&[...document.querySelectorAll('#editor label')].some(l=>l.textContent==='Partner')", 'a new Tag Duel CPU gets a partner')
                await verify("(()=>{const box=[...document.querySelectorAll('#editor .cpu-dialogue textarea')];const t=cpuMetadata.templates.find(t=>t.slot===113);return box.length===28&&box[0].value===t.talk[0];})()", 'added CPUs show the template dialogue')
                await js("project.opponents.pop();selected=0;changed();list();editor()")
                await js("$('#listSearch').value='';list()")
                await js("setTab('banlists');$('#add').click()")
                await verify("[...document.querySelectorAll('dialog[open] button')].some(b=>b.textContent==='Classic banlist')", 'new list offers a choice')
                await js("[...document.querySelectorAll('dialog[open] button')].find(b=>b.textContent==='Points list').click();copyPointsPreset(current())")
                await verify("current().name==='Retro-Genesys 0.2'&&Object.keys(current().cards).length>100&&Object.keys(current().cards).every(r=>byRef.has(r))", 'Retro-Genesys copies only Base game cards')
                await js("$('#undo').click()")
                await verify("Object.keys(current().cards).length===0", 'preset replacement can be undone')
                await js("$('#redo').click();document.querySelector('[aria-label=\"Search list cards\"]').value='Pot of Greed';document.querySelector('[aria-label=\"Search list cards\"]').dispatchEvent(new Event('input'))")
                await verify("[...document.querySelectorAll('.banlist-row')].filter(x=>!x.hidden).length===1", 'list card search filters entries')
                await js("(()=>{const input=[...document.querySelectorAll('.banlist-row')].find(x=>!x.hidden).querySelector('input');input.value=99;input.dispatchEvent(new Event('change'));input.value=100;input.dispatchEvent(new Event('change'));})()")
                await verify("current().cards[resolve('Pot of Greed').ref]===99", 'points accept 99 and reject 100')
                await js("setTab('patches')")
                await verify("$('.inspector').hidden&&[...document.querySelectorAll('.patch-option input')].some(x=>x.disabled)", 'patches hide card controls and require donor assets')
                await js("setTab('decks');$('#listSearch').value='';list();selected=project.decks.find(d=>d.file.startsWith('user_')).file;editor()")
                await command('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': str(downloads.resolve())})
                await js("(()=>{const field=[...document.querySelectorAll('#editor label')].find(x=>x.textContent==='Project label');const input=document.getElementById(field.htmlFor);input.focus();input.select();})()")
                await command('Input.insertText', {'text': 'Shortcut saved deck'})
                await command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 's', 'code': 'KeyS', 'modifiers': 2,
                                                          'windowsVirtualKeyCode': 83})
                await command('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 's', 'code': 'KeyS', 'modifiers': 2,
                                                          'windowsVirtualKeyCode': 83})
                await verify("current().name==='Shortcut saved deck'&&!dirty", 'Ctrl+S commits the focused field before saving')
                for _ in range(50):
                    if (downloads / 'project.wcmod.json').exists():
                        break
                    await asyncio.sleep(.1)
                saved = json.loads((downloads / 'project.wcmod.json').read_text())
                (args.output / 'downloaded-project.wcmod.json').write_text(json.dumps(saved, indent=2))
                assert saved['format_version'] == 2 and any(d['name'] == 'Shortcut saved deck' for d in saved['sections']['decks']['items'])
                await js("$('#undo').click()")
                await verify("dirty&&current().name!=='Shortcut saved deck'", 'Undo after saving tracks unsaved changes')
                await js("$('#redo').click()")
                await verify("!dirty&&current().name==='Shortcut saved deck'", 'Redo back to saved content clears unsaved state')
                for width, name in [(1500, 'desktop'), (800, 'compact')]:
                    await command('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1050,
                                                                          'deviceScaleFactor': 1, 'mobile': False})
                    screenshot = await command('Page.captureScreenshot', {'format': 'png'})
                    (args.output / f'{name}.png').write_bytes(base64.b64decode(screenshot['data']))
                    await verify("document.documentElement.scrollWidth<=innerWidth", name+' layout has no horizontal overflow')
                await verify("document.querySelector('.library').getBoundingClientRect().height<innerHeight&&document.querySelector('.inspector').getBoundingClientRect().top<innerHeight*2", 'compact library stays bounded and Cards remains reachable')
                assert not errors, errors
                print('PASS: no browser exceptions', flush=True)
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--chrome', default='google-chrome')
    parser.add_argument('--output', type=Path, default=Path('build/community-editor-ux-check'))
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    asyncio.run(check(options))
