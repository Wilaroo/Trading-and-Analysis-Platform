// Shared mockup fragments so each option file stays tiny.
const TOPBAR = `
<div class="topbar">
  <div class="left">
    <span class="brand">SENTCOM</span>
    <span class="pill live">● IB LIVE</span><span class="pill">SCANNER ON</span>
    <span class="pill warn">REGIME · NEUTRAL</span><span class="pill">acct $248,310</span>
  </div>
  <div style="display:flex;gap:22px">
    <div class="metric"><div class="l">Day P&L</div><div class="v green">+$1,284.50</div></div>
    <div class="metric"><div class="l">Open Risk</div><div class="v">$612</div></div>
    <div class="metric"><div class="l">Win Rate</div><div class="v">67%</div></div>
  </div>
</div>`;

function tabbar(active){
  const t = (k,lbl,cnt,sub,dot)=>`<div class="tab ${k} ${active===k?'active':''}">${dot?'<span class="dot"></span>':''}<div class="row1"><span class="lbl">${lbl}</span><span class="cnt">${cnt}</span></div><div class="sub">${sub}</div></div>`;
  return `<div class="tabbar">
    ${t('scan','Scan','23','scanning 480',true)}
    ${t('eval','Eval','6','2 gated',false)}
    ${t('order','Order','3','1q+2@ib',false)}
    ${t('manage','Manage','5','+$842 unreal',false)}
    ${t('close','Close','48','WR 64%',false)}
  </div>`;
}

const CLOSE_HD = `<div class="closehd">
  <div class="summary"><span>Trades <b class="tnum">48</b></span><span>WR <b class="green">64%</b></span><span>Net <b class="green">+$3,914</b></span><span>Σ <b class="tnum">+18.4R</b></span><span>worst <b class="red">−1.2R</b></span></div>
  <div class="range"><button>Today</button><button class="on">7d</button><button>30d</button></div>
</div>`;

const ROWS = [
 ['NVDA','gap_and_go','A','gA','L','green','200','121.40','124.85','09:41','10:58','1h17m','+$690','green','+3.4R','green','−0.3/+3.6','target','T2H'],
 ['META','pullback','A','gA','L','green','80','604.10','612.40','09:58','11:40','1h42m','+$664','green','+2.0R','green','−0.4/+2.3','trail','T2H'],
 ['TSLA','vwap_fade','B+','gB','S','red','120','248.10','243.90','10:03','10:46','43m','+$504','green','+1.6R','green','−0.5/+1.8','target','M2M'],
 ['AMD','orb','B','gB','L','green','150','168.20','166.85','10:22','10:51','29m','−$202','red','−1.0R','red','−1.1/+0.4','stop','M2M'],
 ['AAPL','breakout','A','gA','L','green','140','229.50','233.10','09:47','11:02','1h15m','+$504','green','+1.9R','green','−0.2/+2.1','target','T2H'],
 ['UBER','breakdown','B+','gB','S','red','300','72.40','73.55','11:14','11:39','25m','−$345','red','−1.2R','red','−1.3/+0.2','stop','M2M'],
 ['GOOGL','pullback','B','gB','L','green','90','178.30','181.20','10:11','13:05','2h54m','+$261','green','+1.3R','green','−0.6/+1.5','EOD','T2H'],
 ['AMZN','gap_and_go','A','gA','L','green','110','201.40','205.90','09:39','11:20','1h41m','+$495','green','+2.2R','green','−0.3/+2.4','target','T2H'],
 ['NFLX','pullback','A','gA','L','green','40','842.00','851.30','10:34','12:18','1h44m','+$372','green','+1.5R','green','−0.4/+1.7','target','T2H'],
 ['CRM','orb','B+','gB','S','red','160','328.50','330.10','11:02','11:21','19m','−$256','red','−0.8R','red','−0.9/+0.3','stop','M2M'],
];

function fullTable(){
  const head = `<thead><tr><th class="l">Sym</th><th class="l">Setup</th><th>TQS</th><th>Dir</th><th>Sh</th><th>Entry</th><th>Exit</th><th>In</th><th>Out</th><th>Hold</th><th>P&L</th><th>R</th><th>MAE/MFE</th><th class="l">Reason</th><th>Type</th></tr></thead>`;
  const body = ROWS.map(r=>`<tr>
    <td class="l tnum">${r[0]}</td><td class="l">${r[1]}</td>
    <td class="${r[3]==='gA'?'green':'mono'}" ${r[3]==='gB'?'style="color:var(--blue)"':''}>${r[2]}</td>
    <td class="${r[5]}">${r[4]}</td><td>${r[6]}</td><td>${r[7]}</td><td>${r[8]}</td><td>${r[9]}</td><td>${r[10]}</td><td>${r[11]}</td>
    <td class="${r[13]} tnum">${r[12]}</td><td class="${r[15]}">${r[14]}</td><td>${r[16]}</td><td class="l">${r[17]}</td><td>${r[18]}</td>
  </tr>`).join('');
  return `<table>${head}<tbody>${body}</tbody></table>`;
}

function compactList(){
  return ROWS.map(r=>`<div class="crow">
    <div class="l"><span class="sym">${r[0]}</span><span class="gchip ${r[3]}">${r[2]}</span><span class="rsn">${r[17]}</span></div>
    <div class="r"><span class="${r[15]}">${r[14]}</span><span class="${r[13]} tnum">${r[12]}</span></div>
  </div>`).join('');
}

const RIGHTCOL = `
  <div class="brief"><span class="t">◆ Morning Briefing</span><span class="mono" style="color:var(--t3);font-size:11px">3 watch</span></div>
  <div class="panel" style="flex:1">
    <div class="stream-hd"><span class="t">◇ Bot Narrative Stream</span><span class="mono" style="color:var(--t4);font-size:10px">live</span></div>
    <div class="stream">
      <div class="thought buy"><div class="ts">11:14 · NVDA</div><div class="tx"><b>Entered LONG 200sh.</b> TQS A (88). Regime SPY/QQQ/IWM neutral.</div></div>
      <div class="thought scan"><div class="ts">11:13 · AAPL</div><div class="tx">Eval gap_and_go — gate 0.61 &lt; 0.66. Holding.</div></div>
      <div class="thought warn"><div class="ts">11:12 · AMD</div><div class="tx">AMD nearing stop. MAE −0.6R.</div></div>
      <div class="thought"><div class="ts">11:11 · MARKET</div><div class="tx">SPY −0.2% / QQQ +0.3% — <b>divergence</b>, size 0.8×.</div></div>
      <div class="thought buy"><div class="ts">10:58 · META</div><div class="tx"><b>Target 1 hit (+1.0R).</b> Trail to BE.</div></div>
    </div>
  </div>`;

function paintCandles(id){
  const c=document.getElementById(id); if(!c) return; let p=60;
  for(let i=0;i<40;i++){const up=Math.random()>0.42;p+=(up?1:-1)*(2+Math.random()*6);p=Math.max(20,Math.min(150,p));
    const el=document.createElement('div');el.className='cnd';el.style.height=(30+(p/150)*150)+'px';
    el.style.background=up?'rgba(52,211,153,.65)':'rgba(251,113,133,.65)';c.appendChild(el);}
}
