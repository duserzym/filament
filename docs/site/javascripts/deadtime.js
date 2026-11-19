/* Pure numerical functions first; browser wiring below. No dates are calculated here. */
(function (root) {
  'use strict';
  const pairs = [[206,204],[206,207],[206,205],[207,205],[204,205],[208,205]];
  const labels = pairs.map(([a,b]) => `${a}/${b}`);
  function correctObserved(observed, tauNs) {
    const factor = 1-observed*tauNs*1e-9;
    if (!(factor > 0) || observed < 0) throw new RangeError('Rate is outside the non-paralysable domain.');
    return observed/factor;
  }
  function changeNet(net, baseline, deltaNs) {
    const gross = net+baseline;
    const factor = 1-gross*deltaNs*1e-9;
    if (!(factor > 0)) throw new RangeError('Dead-time change saturates this rate.');
    return gross/factor-baseline;
  }
  function maskedStats(values, mask) {
    const active = values.filter((x,i) => mask[i] && Number.isFinite(x));
    const n = active.length;
    if (n < 2) throw new RangeError('At least two usable cycles are required.');
    const mean = active.reduce((s,x) => s+x,0)/n;
    const sd = Math.sqrt(active.reduce((s,x) => s+(x-mean)*(x-mean),0)/(n-1));
    return {mean, se_pct: sd/Math.sqrt(n)/mean*100, n};
  }
  function cycleRatios(data, tauNs) {
    const d = {}, delta = tauNs-data.tau0;
    Object.keys(data.daly).forEach(m => {
      d[m] = data.daly[m].map((x,i) => delta === 0 ? x : changeNet(x,data.baseline[i],delta));
    });
    const gain = d[206].map((x,i) => data.faraday206[i]/x);
    const ratios = {};
    pairs.forEach(([a,b],k) => {
      const name = labels[k];
      ratios[name] = delta === 0 && data.acquired_ratios ? data.acquired_ratios[name].slice() :
        d[b].map((x,i) => a === 208 ? data.faraday208[i]/(gain[i]*x) : d[a][i]/x);
    });
    return {daly:d, gain, ratios};
  }
  function firstOrder(data, name, deltaNs) {
    const [a,b] = name.split('/').map(Number), numerator = a === 208 ? 206 : a;
    const old = cycleRatios(data,data.tau0).ratios[name], mask = data.masks[name];
    let sum=0, weighted=0;
    old.forEach((x,i) => {
      if (!mask[i]) return;
      const na=data.daly[numerator][i], nb=data.daly[b][i], B=data.baseline[i];
      sum += x;
      weighted += x*((na+B)*(na+B)/na-(nb+B)*(nb+B)/nb);
    });
    return weighted/sum*deltaNs*1e-9*100;
  }
  function evaluate(data,tauNs) {
    const cycles=cycleRatios(data,tauNs), ratios={};
    labels.forEach(name => {ratios[name]=maskedStats(cycles.ratios[name],data.masks[name]);});
    return {ratios,cycles};
  }
  function gridEntry(data,tauNs) {
    const tick=Math.round(tauNs*10), index=tick-Math.round(data.grid[0].tau*10);
    if (Math.abs(tauNs-tick/10)>1e-10 || index<0 || index>=data.grid.length) throw new RangeError('Choose a grid dead time.');
    return data.grid[index];
  }
  function ratioBias(na,nb,deltaNs) {
    const x=na*deltaNs*1e-9, y=nb*deltaNs*1e-9;
    if (!(1-x>0) || !(1-y>0)) throw new RangeError('Rate is outside the correction domain.');
    return {exact:((1-y)/(1-x)-1)*100, first:(na-nb)*deltaNs*1e-9*100};
  }
  function cycleChanges(data, tauNs, name) {
    const [a,b]=name.split('/').map(Number);
    if (!data.daly[a] || !data.daly[b]) throw new RangeError('Choose a Daly/Daly ratio.');
    const original=cycleRatios(data,data.tau0).ratios[name];
    const selected=cycleRatios(data,tauNs).ratios[name];
    const difference=data.daly[a].map((n,i)=>(n+data.baseline[i])-(data.daly[b][i]+data.baseline[i]));
    return {difference, percent:selected.map((r,i)=>(r/original[i]-1)*100),
      first:difference.map(x=>100*x*(tauNs-data.tau0)*1e-9)};
  }
  function breakBlocks(x, y, blocks) {
    const result={x:[],y:[]};
    x.forEach((value,i)=>{
      if (i>0 && blocks[i]!==blocks[i-1]) {result.x.push(null);result.y.push(null);}
      result.x.push(value);result.y.push(y[i]);
    });
    return result;
  }
  const api={pairs,labels,correctObserved,changeNet,maskedStats,cycleRatios,firstOrder,evaluate,gridEntry,ratioBias,cycleChanges,breakBlocks};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  if (root) root.FilamentDeadtime=api;
  if (typeof document === 'undefined') return;

  function mount() {
    const lab=document.getElementById('deadtime-lab');
    if (!lab || lab.dataset.ready) return;
    const data=root.FILAMENT_Z1;
    if (!data) return;
    lab.dataset.ready='yes';
    const slider=document.getElementById('tau-slider'), output=document.getElementById('tau-value');
    const baseline=evaluate(data,data.tau0), dates0=gridEntry(data,data.tau0).dates;
    const dateLabels=['206/238','207/235','207/206'];
    const colors=['#007f91','#cf5a1b','#7c63b6','#5b9440'];
    const num=(x,n=9) => Number(x).toPrecision(n);
    const signed=(x,n=4) => (x>=0?'+':'')+Number(x).toFixed(n);
    function palette() {
      // Resolve CSS custom colors to rgb(a); Plotly does not understand all
      // modern hsl/hsla forms used by Material's slate palette.
      const probe=document.createElement('span');
      probe.style.color='var(--md-default-fg-color)';
      probe.style.backgroundColor='var(--md-code-bg-color)';
      document.body.appendChild(probe);
      const style=getComputedStyle(probe);
      const result={fg:style.color,bg:style.backgroundColor,
        dark:document.body.getAttribute('data-md-color-scheme')==='slate'};
      probe.remove(); return result;
    }
    function plot(id,traces,title,xaxis,yaxis,extras={}) {
      const el=document.getElementById(id); if (!el || !root.Plotly) return;
      const p=palette(), narrow=el.clientWidth<430;
      let heading=title;
      if (narrow && title.length>28) {
        const split=title.includes(' · ') ? title.indexOf(' · ') : title.lastIndexOf(' ',28);
        heading=title.slice(0,split)+'<br>'+title.slice(split).replace(/^ · |^ /,'');
      }
      root.Plotly.react(el,traces,{title:{text:heading,font:{size:narrow?13:15}},
        height:narrow?410:370,margin:{l:65,r:20,t:62,b:narrow?125:65},
        font:{color:p.fg,size:12},paper_bgcolor:p.bg,plot_bgcolor:p.bg,
        colorway:colors,xaxis:{...xaxis,automargin:true,gridcolor:p.dark?'#384050':'#e3e8eb'},
        yaxis:{...yaxis,automargin:true,gridcolor:p.dark?'#384050':'#e3e8eb'},
        legend:{orientation:'h',y:narrow?-.42:-.23,font:{size:11}},...extras},
        {responsive:true,displaylogo:false,modeBarButtonsToRemove:['lasso2d','select2d'],scrollZoom:false});
    }
    function updateTau() {
      const tau=Math.round(Number(slider.value)*10)/10;
      output.textContent=tau.toFixed(1)+' ns';
      const result=evaluate(data,tau), entry=gridEntry(data,tau);
      document.getElementById('ratio-results').innerHTML=labels.map(name => {
        const st=result.ratios[name], old=baseline.ratios[name];
        return `<tr><th scope="row">${name}</th><td>${num(st.mean,8)}</td><td>${num(st.se_pct,4)}</td><td>${signed((st.mean/old.mean-1)*100)}</td><td>${signed(firstOrder(data,name,tau-data.tau0))}</td></tr>`;
      }).join('');
      document.getElementById('date-results').innerHTML=dateLabels.map(name => {
        const [t,s]=entry.dates[name];
        return `<tr><th scope="row">${name}</th><td>${t.toFixed(3)} ± ${s.toFixed(3)}</td><td>${signed(t-dates0[name][0],3)}</td></tr>`;
      }).join('');
      const changes=['206/207','206/205'].map(name=>({name,...cycleChanges(data,tau,name)}));
      const changeTraces=changes.map((c,i)=>({x:c.difference,y:c.percent,type:'scatter',mode:'markers',
        name:c.name,marker:{color:colors[i],size:6,opacity:.7},
        hovertemplate:`${c.name}<br>Rate difference: %{x:.1f} cps<br>Change: %{y:.4f}%<extra></extra>`}));
      const low=Math.min(...changes.flatMap(c=>c.difference)), high=Math.max(...changes.flatMap(c=>c.difference));
      changeTraces.push({x:[low,high],y:[low,high].map(x=>100*x*(tau-data.tau0)*1e-9),
        type:'scatter',mode:'lines',name:'First order',line:{color:palette().fg,dash:'dash'}});
      document.getElementById('change-status').textContent=tau===data.tau0
        ? 'Move the slider to see how each cycle changes.'
        : 'Each dot is one cycle. The dashed line uses the gross-rate first-order approximation.';
      plot('change-plot',changeTraces,"Each cycle’s change tracks its beam intensity",
        {title:'Acquired gross rate difference (cps)'},{title:'Ratio change (%)',tickformat:'.4f'});
      const line=(y,name,color) => ({...breakBlocks(data.seconds,y,data.block),type:'scatter',mode:'lines',
        connectgaps:false,name,line:{color,width:1.4}});
      const cycleTraces=[line(baseline.cycles.ratios['206/207'],`acquired (${data.tau0.toFixed(1)} ns)`,colors[0])];
      if (tau!==data.tau0) cycleTraces.push(line(result.cycles.ratios['206/207'],`selected (${tau.toFixed(1)} ns)`,colors[1]));
      cycleTraces.push({x:data.seconds.filter((_,i)=>!data.masks['206/207'][i]),
         y:result.cycles.ratios['206/207'].filter((_,i)=>!data.masks['206/207'][i]),
         mode:'markers',type:'scatter',name:'Excluded by saved mask',marker:{symbol:'x',size:7,color:colors[2]}});
      plot('cycle-plot',cycleTraces,
        'Cycle 206/207 · fixed saved selection',{title:'Seconds since run start'},{title:'206/207'});
      const dateTraces=[];
      dateLabels.forEach((name,i) => {
        dateTraces.push({x:data.grid.map(g=>g.tau),y:data.grid.map(g=>g.dates[name][0]-dates0[name][0]),
          type:'scatter',mode:'lines',name,line:{color:colors[i]}});
        dateTraces.push({x:[tau],y:[entry.dates[name][0]-dates0[name][0]],type:'scatter',mode:'markers',
          showlegend:false,marker:{color:colors[i],size:9},name});
      });
      plot('date-plot',dateTraces,'Dates from the age engine',{title:'Dead time (ns)'},{title:'Date shift (Ma)'});
    }
    function countPlots() {
      const taus=[20,data.tau0,40,60], x=Array.from({length:200},(_,i)=>10**(i*7/199));
      const rateTraces=[{x,y:x,mode:'lines',name:'1:1',line:{color:palette().fg,dash:'dot'}}], percent=[];
      taus.forEach((tau,i) => {
        const y=x.map(n=>correctObserved(n,tau));
        rateTraces.push({x,y,name:`${tau} ns`,mode:'lines',line:{color:colors[i]}});
        percent.push({x,y:y.map((n,k)=>(n/x[k]-1)*100),name:`${tau} ns`,mode:'lines',line:{color:colors[i]}});
      });
      Object.keys(data.daly).forEach(m => {
        const net=data.daly[m].reduce((s,x)=>s+x,0)/data.daly[m].length;
        const B=data.baseline.reduce((s,x)=>s+x,0)/data.baseline.length;
        const N=net+B, obs=N/(1+N*data.tau0*1e-9);
        rateTraces.push({x:[obs],y:[N],mode:'markers+text',text:[m],textposition:'top center',
          name:`Mass ${m}`,showlegend:false,marker:{size:8,color:palette().fg}});
        percent.push({x:[obs],y:[(N/obs-1)*100],mode:'markers+text',text:[m],textposition:'top center',
          showlegend:false,marker:{size:8,color:palette().fg}});
      });
      plot('rate-plot',rateTraces,'Corrected versus observed rate',{title:'Observed gross rate (cps)',type:'log'},
           {title:'Corrected gross rate (cps)',type:'log'});
      plot('percent-plot',percent,'How much is added?',{title:'Observed gross rate (cps)',type:'log'},
           {title:'Correction (%)'});
    }
    function biasPlot() {
      const input=document.getElementById('denominator-rate'), nb=Number(input.value);
      const status=document.getElementById('bias-status');
      if (!Number.isFinite(nb) || nb<=0 || nb>=2e6) {status.textContent='Enter a positive rate below 2,000,000 cps.';return;}
      status.textContent='Exact solid · first order dashed. Markers use this chosen denominator.';
      const xs=Array.from({length:160},(_,i)=>10**(-4+i*5/159));
      const traces=[];
      [1,2,40-data.tau0,5].forEach((dt,i) => {
        const b=xs.map(r=>ratioBias(r*nb,nb,dt));
        traces.push({x:xs,y:b.map(x=>x.exact),mode:'lines',name:`Δτ ${num(dt,2)} ns`,line:{color:colors[i]}});
        traces.push({x:xs,y:b.map(x=>x.first),mode:'lines',showlegend:false,line:{color:colors[i],dash:'dash'}});
      });
      // Both example ratios use the 205 denominator; changing nb scales their
      // intensity pattern deliberately, rather than mislabelling unlike beams.
      const mean=m=>data.daly[m].reduce((s,x)=>s+x,0)/data.daly[m].length;
      [204,206,207].forEach(m=>{
        const r=mean(m)/mean(205), bias=ratioBias(r*nb,nb,40-data.tau0);
        traces.push({x:[r],y:[bias.exact],mode:'markers+text',text:[`${m}/205`],textposition:'top center',
          name:`${m}/205 intensity pattern`,showlegend:false,marker:{size:8,color:palette().fg}});
      });
      plot('bias-plot',traces,'Ratio bias at a chosen denominator rate',
           {title:'Gross intensity ratio Nₐ/Nᵦ',type:'log'},{title:'Ratio change (%)'});
    }
    slider.min=data.grid[0].tau;slider.max=data.grid.at(-1).tau;slider.step=.1;slider.value=data.tau0;
    document.getElementById('denominator-rate').value=(data.daly[205].reduce((s,x)=>s+x,0)/data.daly[205].length).toFixed(0);
    slider.addEventListener('input',updateTau);
    document.querySelectorAll('[data-tau]').forEach(b=>b.addEventListener('click',()=>{slider.value=b.dataset.tau;updateTau();}));
    document.getElementById('denominator-rate').addEventListener('input',biasPlot);
    function redraw(){
      const next=palette().dark ? ['#58c4cf','#f2a16d','#b49cde','#add387'] : ['#007f91','#cf5a1b','#7c63b6','#5b9440'];
      colors.splice(0,colors.length,...next); updateTau();countPlots();biasPlot();
    }
    if (!root.Plotly) document.getElementById('plot-status').textContent='Tables work offline. Load the pinned Plotly CDN script to display plots.';
    redraw();
    new MutationObserver(redraw).observe(document.body,{attributes:true,attributeFilter:['data-md-color-scheme']});
  }
  if (typeof document$ !== 'undefined') document$.subscribe(mount);
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',mount); else mount();
})(typeof window !== 'undefined' ? window : null);
