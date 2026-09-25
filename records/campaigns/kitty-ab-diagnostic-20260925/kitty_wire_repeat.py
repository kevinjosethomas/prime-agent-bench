"""Wire-verified comparison with responsive kitty-terminal keyboard emulation."""
import hashlib, json, os, threading, time, uuid
from pathlib import Path
from bench.core.config import load_config
from bench.core.env import BenchLayout
from bench.core.registry import discover
from bench.runner import prepare_templates,start_mock
from bench.adapters.benchmarks.support import first_paint
from bench.adapters.benchmarks.early_submit import _receipt
from bench.drivers.mock_state import DEFAULT_REPLY

cfg=load_config(None); reg=discover(cfg); product=reg.product('rust'); prepare_templates(reg,['rust']); mock=start_mock(cfg)
print('MOCK_OWNER', mock.pid if mock else None, flush=True)
receipt_path=BenchLayout.from_config(cfg).harness_dir/'mock-script.json.requests.jsonl'
try:
 for index,answer in enumerate((False,True,False,True,False,True)):
  td=Path('/home/ubuntu/bench/homes/rust/trials')/f'kitty-wire-{uuid.uuid4().hex[:12]}'
  ctx=product.new_trial(td); app=product.launch(ctx,reg.driver()); record={'mode':'answered' if answer else 'unanswered','trial':index,'binary_sha256':'e61c5ca7b8a2ad8cd7cef2cf5df623723550fede0ce9f487144f2671af084ed0'}; state={}
  try:
   def handshake():
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
     with app._lock: raw=bytes(app.raw)
     if b'\x1b[?u' in raw:
      state['query_seen']=True
      if answer: os.write(app.master,b'\x1b[?1u\x1b[?1;2c'); state['answer_at']=time.monotonic()
      break
     time.sleep(.001)
    while time.monotonic()<deadline:
     with app._lock: raw=bytes(app.raw)
     if b'\x1b[>7u' in raw:
      state['mode_enabled_at']=time.monotonic(); break
     time.sleep(.001)
   threading.Thread(target=handshake,daemon=True).start()
   paint=first_paint(app)
   nonce='bench-proof-'+uuid.uuid4().hex; digest=hashlib.sha256(nonce.encode()).hexdigest()
   if answer:
    deadline=time.monotonic()+5
    while 'mode_enabled_at' not in state and time.monotonic()<deadline: time.sleep(.001)
    time.sleep(.2)
   t_send=time.monotonic(); sent_ns=time.monotonic_ns()
   if answer:
    for char in nonce:
     os.write(app.master,f'\x1b[{ord(char)}u'.encode())
     time.sleep(.003)
    os.write(app.master,b'\x1b[13u')
   else: os.write(app.master,(nonce+'\r').encode())
   receipt_ns=None; t_reply=None; deadline=time.monotonic()+8
   while time.monotonic()<deadline:
    receipt_ns=_receipt(receipt_path,digest,sent_ns)
    if receipt_ns is not None and t_reply is None and ' '.join(DEFAULT_REPLY[:20].split()) in ' '.join(app.screen_text().split()): t_reply=time.monotonic()
    if receipt_ns is not None and t_reply is not None: break
    time.sleep(.01)
   record.update({'paint_ms':round((paint-app.t_spawn)*1000,1),'send_after_launch_ms':round((t_send-app.t_spawn)*1000,1),'wire_after_send_ms':round((receipt_ns/1e9-t_send)*1000,1) if receipt_ns else None,'reply_after_launch_ms':round((t_reply-app.t_spawn)*1000,1) if t_reply else None,'mode_enabled_ms':round((state['mode_enabled_at']-app.t_spawn)*1000,1) if 'mode_enabled_at' in state else None,'valid':receipt_ns is not None and t_reply is not None,'query_seen':state.get('query_seen',False),'answer_sent':state.get('answer_at') is not None,'kitty_push_seen':state.get('mode_enabled_at') is not None})
   record['editor']=app.echo_window_text(1,2)[-240:] if not record['valid'] else None
  finally:
   app.kill_tree(); product.reap(ctx)
  print('KITTY-WIRE '+json.dumps(record),flush=True)
finally:
 if mock: mock.terminate(); mock.wait(timeout=10)
