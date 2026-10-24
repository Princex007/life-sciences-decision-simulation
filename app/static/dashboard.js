/* Results dashboard: KPIs, assumptions, trace-generated flowchart, time series,
   driver effects, decision audit, and driver-variant comparison. */

const SVG_NS='http://www.w3.org/2000/svg';
const SERIES_FALLBACK=['#0d766e','#c2703d','#3f6ea5','#8a5aa8','#2f8f5b','#b04a5a','#6b7a2f','#4a6f7a'];
function seriesColor(index){const tokens=getComputedStyle(document.documentElement);
  return tokens.getPropertyValue(`--series-${(index%SERIES_FALLBACK.length)+1}`).trim()||SERIES_FALLBACK[index%SERIES_FALLBACK.length];}
function edgeColor(status){const tokens=getComputedStyle(document.documentElement);
  const key=status==='pruned'?'--edge-pruned':'--edge';
  return tokens.getPropertyValue(key).trim()||(status==='pruned'?'#c3cfcb':'#8fa9a3');}
const MAX_FLOW_NODES=300;
const DECISION_SOURCE_HELP={
  objective_scorer:'Chosen because the configured evaluation objective scored it clearly above the runner-up.',
  existing_policy_fallback:'Score margin was inside the tie tolerance, or scoring was unavailable, so the configured rule-based policy chose. This is a configured preference, not evidence of correctness.',
  llm:'An LLM chose this action. LLM selection is never evidence that the action is objectively correct.'
};

function svgEl(tag,attrs={}){const el=document.createElementNS(SVG_NS,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));return el;}
function fmt(value){
  if(value==null)return '—';
  if(typeof value!=='number'||!isFinite(value))return String(value);
  const abs=Math.abs(value);
  if(abs>=1e7||(abs>0&&abs<1e-3))return value.toExponential(2);
  return Number(value.toFixed(abs>=100?1:4)).toLocaleString();
}
function shortName(scenario){
  const parts=(scenario.name||scenario.scenario_id).split(' / ');
  const tail=parts[parts.length-1]||scenario.scenario_id;
  return tail.length>34?`${tail.slice(0,33)}…`:tail;
}
function tableFrom(headers,rows){
  const table=document.createElement('table');const head=document.createElement('thead');const headRow=document.createElement('tr');
  headers.forEach(text=>{const th=document.createElement('th');th.textContent=text;headRow.append(th);});
  head.append(headRow);table.append(head);
  const body=document.createElement('tbody');
  rows.forEach(cells=>{const tr=document.createElement('tr');cells.forEach(cell=>{const td=document.createElement('td');
    if(cell instanceof Node)td.append(cell);else td.textContent=cell??'—';tr.append(td);});body.append(tr);});
  table.append(body);
  const wrap=document.createElement('div');wrap.className='table-wrap';wrap.append(table);return wrap;
}
function scrollBox(node){const wrap=document.createElement('div');wrap.className='table-wrap';wrap.append(node);return wrap;}
function diffVariables(before,after){
  const keys=new Set([...Object.keys(before||{}),...Object.keys(after||{})]);
  return [...keys].filter(key=>JSON.stringify(before?.[key])!==JSON.stringify(after?.[key])).map(key=>({variable:key,to:after?.[key]}));
}

function clearDashboard(){
  const reset=(id,text)=>{const box=byId(id);if(!box)return;box.replaceChildren(document.createTextNode(text));box.classList.add('muted');};
  reset('assumptions','Run a simulation to see the evidence grading behind these results.');
  reset('flowchart','The flowchart appears here after a run.');
  reset('timeseries','Run a simulation to plot state trajectories.');
  reset('driverEffects','This run has no external drivers, or none were active.');
  reset('variantComparison','Use “Compare all variants” on a driver card to fill this panel.');
  byId('decisionAudit').querySelector('thead').replaceChildren();
  byId('decisionAudit').querySelector('tbody').replaceChildren();
  byId('decisionAuditSummary').replaceChildren();
  reset('decisionAuditEmpty','Run a simulation to audit decisions.');
}

function renderDashboard(results,definition){
  const scenarios=results.scenarios||[];
  drawSummary(results.summary);
  drawAssumptions(results.summary,definition);
  drawTree(results.root,scenarios);
  drawFlowchart(results.root,scenarios);
  drawComparison(scenarios);
  drawCharts(scenarios,results.summary);
  drawTimeSeries(scenarios,definition,results.summary);
  drawDriverEffects(results);
  drawDecisionAudit(scenarios);
}

function drawSummary(summary){
  const box=byId('summary');box.replaceChildren();box.classList.remove('muted');
  const cards=[['Terminal scenarios',summary.terminal_scenarios],['Pruned nodes',summary.pruned_nodes],
    ['Duration (s)',Number(summary.duration_seconds||0).toFixed(3)],['Horizon',`${summary.time_horizon} ${summary.step_unit||'step'}s`],
    ['Forecast model',(summary.forecast_model||'none').replaceAll('_',' ')],['Scenario policy',summary.scenario_policy],
    ['Decision policy',(summary.decision_policy||'').replaceAll('_',' ')],
    ['Active drivers',(summary.key_drivers||[]).length?(summary.key_drivers||[]).join(', '):'none']];
  const analogue=summary.reference_history;
  if(summary.forecast_model==='reference_product'&&analogue&&!analogue.missing){
    cards.push(['Reference analogue',analogue.scale==null?analogue.name
      :`${analogue.name} ×${fmt(analogue.scale)}`]);
  }
  const usage=summary.llm_usage;
  if(usage){
    cards.push(['Provider calls',usage.provider_calls],['Tokens reported',usage.total_tokens||0]);
    if(usage.skipped_calls)cards.push(['Calls skipped by budget',usage.skipped_calls]);
  }
  cards.forEach(([label,value])=>{const card=document.createElement('div');card.className='metric';
    const strong=document.createElement('b');strong.textContent=value;
    const small=document.createElement('span');small.textContent=label;card.append(strong,small);box.append(card);});
  if(usage&&usage.exhausted_reason){
    box.append(note(`${usage.exhausted_reason} ${usage.skipped_calls} decision(s) were made by the configured rule-based policy instead of a model. A model did not choose them.`,'assumption-note'));
  }
  if(usage&&usage.provider_calls&&!usage.skipped_calls){
    box.append(note(`A provider selected ${usage.provider_calls} decision(s) using ${usage.models?.join(', ')||'an unreported model'}. Provider selection is not evidence that a decision is correct in the real world.`));
  }
}

function drawAssumptions(summary,definition){
  const box=byId('assumptions');box.replaceChildren();box.classList.remove('muted');
  const driverLabels=summary.assumption_labels||[];
  if(driverLabels.length){
    const section=document.createElement('div');section.className='assumption-group';
    const heading=document.createElement('b');heading.textContent='External-driver assumptions';section.append(heading);
    const list=document.createElement('ul');driverLabels.forEach(text=>{const li=document.createElement('li');li.textContent=text;list.append(li);});
    section.append(list);box.append(section);
  }
  const analogue=summary.reference_history;
  if(analogue&&!analogue.missing&&definition?.reference_history_id){
    const section=document.createElement('div');section.className='assumption-group';
    const heading=document.createElement('b');heading.textContent='Reference analogue';section.append(heading);
    section.append(tableFrom(['Item','Value'],[
      ['Series borrowed',`${analogue.name} · ${analogue.points} recorded periods, graded `
        +String(analogue.evidence_grade||'unspecified').replaceAll('_',' ')
        +` from ${analogue.source||'an unstated source'}`],
      ['Peak you entered',definition.reference_peak==null?'not set':fmt(definition.reference_peak)],
      ['Rescaling applied',analogue.scale==null?'none (no peak)':`${fmt(analogue.scale)}× every recorded period`],
      ['Why this product',definition.reference_rationale||'chosen by you without a recorded reason'],
      ['Profile it was matched against',definition.reference_profile||'no profile was written']]));
    section.append(note('The ramp shape is another product\'s recorded history; the peak level and the '
      +'choice of analogue are assumptions. Neither is evidence that this product will sell like that one.'));
    box.append(section);
  }
  const evidence=summary.variable_evidence||{};
  const names=Object.keys(evidence);
  const section=document.createElement('div');section.className='assumption-group';
  const heading=document.createElement('b');heading.textContent='World variable evidence grades';section.append(heading);
  if(!names.length){section.append(note('No evidence grades were recorded in world_variable_metadata, so every value below should be treated as an ungraded assumption.'));}
  else{
    section.append(tableFrom(['Variable','Grade','Labels'],names.map(name=>{
      const meta=evidence[name]||{};const labels=document.createElement('div');
      (meta.assumption_labels||[]).forEach(text=>{const p=document.createElement('p');p.className='label-line';p.textContent=text;labels.append(p);});
      return [name.replaceAll('_',' '),gradeBadge(meta.evidence_grade),labels];})));
  }
  box.append(section);
  const objectives=Object.keys(definition?.evaluation_objectives||{});
  const objectiveSection=document.createElement('div');objectiveSection.className='assumption-group';
  const objectiveHeading=document.createElement('b');objectiveHeading.textContent='Evaluation objectives';objectiveSection.append(objectiveHeading);
  objectiveSection.append(note(objectives.length
    ? `Configured for: ${objectives.join(', ')}. Component weights are user assumptions; they express preference, not measured truth.`
    : 'None configured. Decisions fall back to the rule-based policy, so results reflect configured defaults rather than an explicit objective.'));
  box.append(objectiveSection);
  const models=Object.keys({...definition?.clinical_outcome_assumptions,...definition?.patient_affordability_assumptions});
  if(models.length){
    const modelSection=document.createElement('div');modelSection.className='assumption-group';
    const modelHeading=document.createElement('b');modelHeading.textContent='Clinical and affordability assumptions';modelSection.append(modelHeading);
    modelSection.append(note(`Configured keys: ${models.join(', ')}. These are user assumptions used by forecast helpers.`));
    box.append(modelSection);
  }
  box.append(note('Nothing in this panel is a market forecast or clinical evidence. Graded values are reported exactly as configured.','assumption-note'));
}

/* ---------- decision flowchart generated from the recorded trace ---------- */
function flowLayout(root,limit){
  const nodes=[];let slot=0;let truncated=false;
  const walk=(node,depth,parent)=>{
    if(nodes.length>=limit){truncated=true;return null;}
    const entry={node,depth,parent,children:[],slot:0};nodes.push(entry);
    (node.children||[]).forEach(child=>{const childEntry=walk(child,depth+1,entry);if(childEntry)entry.children.push(childEntry);});
    if(entry.children.length)entry.slot=entry.children.reduce((sum,item)=>sum+item.slot,0)/entry.children.length;
    else entry.slot=slot++;
    return entry;
  };
  walk(root,0,null);
  return {nodes,truncated};
}
function flowLabel(entry){
  const node=entry.node;const lines=[];
  if(node.node_type==='root')lines.push('Simulation start');
  else if(node.node_type==='decision')lines.push(node.acting_agent||'agent',node.selected_action?.name||'decision');
  else if(node.node_type==='event'){const event=node.triggering_event||{};lines.push(event.event_type||'event',event.description||'');}
  else{
    const before=entry.parent?entry.parent.node.world_state?.variables:{};
    const changes=diffVariables(before,node.world_state?.variables);
    lines.push(changes.length?`Δ ${changes.length} variable${changes.length===1?'':'s'}`:'Transition (no change)',
      changes.slice(0,2).map(change=>`${change.variable.replaceAll('_',' ')} → ${fmt(change.to)}`).join(', '));
  }
  if(node.status==='pruned')lines.push(`pruned: ${node.pruning_reason||node.pruning_policy||''}`);
  else if(node.status==='terminal')lines.push('terminal scenario');
  return lines.filter(Boolean).slice(0,3);
}
function flowClass(node){
  if(node.status==='pruned')return 'flow-pruned';
  if(node.status==='terminal')return 'flow-terminal';
  if(node.node_type==='decision')return node.branch_role==='counterfactual'?'flow-counterfactual':'flow-decision';
  return node.node_type==='root'?'flow-root':'flow-event';
}
function drawFlowchart(root,scenarios){
  const box=byId('flowchart');box.replaceChildren();box.classList.remove('muted');
  if(!root){box.textContent='This run returned no tree.';return;}
  const {nodes,truncated}=flowLayout(root,MAX_FLOW_NODES);
  const scenarioByNode=new Map((scenarios||[]).map(scenario=>[scenario.terminal_node_id,scenario]));
  const W=206,H=70,GX=26,GY=40;
  const maxSlot=Math.max(...nodes.map(entry=>entry.slot),0);
  const maxDepth=Math.max(...nodes.map(entry=>entry.depth),0);
  // Depth-first stacking turns a long run into a diagram thousands of pixels
  // tall, so once the tree outgrows a readable panel walk the trace across rows.
  const chain=maxDepth*(H+GY)+GY>1400;
  const perRow=chain?Math.max(3,Math.min(8,Math.round(Math.sqrt(nodes.length*2)))):maxSlot+1;
  const rows=chain?Math.ceil(nodes.length/perRow):maxDepth+1;
  const width=perRow*(W+GX)+GX,height=rows*(H+GY)+GY;
  const svgRoot=svgEl('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'img','aria-label':'Decision flowchart generated from the recorded simulation trace'});
  const position=new Map();
  nodes.forEach((entry,index)=>position.set(entry.node.node_id,
    {x:GX+(chain?index%perRow:entry.slot)*(W+GX),y:GY+(chain?Math.floor(index/perRow):entry.depth)*(H+GY)}));
  nodes.forEach(entry=>{
    if(!entry.parent)return;
    const from=position.get(entry.parent.node.node_id),to=position.get(entry.node.node_id);
    const cls=`flow-edge${entry.node.status==='pruned'?' is-pruned':''}${entry.node.branch_role==='counterfactual'?' is-counterfactual':''}`;
    const mid=(from.y+H+to.y)/2;
    // Horizontal step within a row, right-angle sweep when the chain wraps.
    const d=Math.abs(to.y-from.y)<1
      ?`M ${from.x+W} ${from.y+H/2} C ${from.x+W+GX/2} ${from.y+H/2}, ${to.x-GX/2} ${to.y+H/2}, ${to.x} ${to.y+H/2}`
      :to.x<from.x
        ?`M ${from.x+W/2} ${from.y+H} L ${from.x+W/2} ${mid} L ${to.x+W/2} ${mid} L ${to.x+W/2} ${to.y}`
        :`M ${from.x+W/2} ${from.y+H} C ${from.x+W/2} ${from.y+H+GY/2}, ${to.x+W/2} ${to.y-GY/2}, ${to.x+W/2} ${to.y}`;
    svgRoot.append(svgEl('path',{class:cls,d,fill:'none','stroke-width':'1.6'}));
  });
  nodes.forEach(entry=>{
    const node=entry.node;const at=position.get(node.node_id);
    const group=svgEl('g',{class:`flow-node ${flowClass(node)}`,transform:`translate(${at.x},${at.y})`});
    group.append(svgEl('rect',{width:W,height:H,rx:'7'}));
    const badge=svgEl('text',{x:'9',y:'15',class:'flow-kind'});
    badge.textContent=`t${node.time} · ${node.node_type}`;group.append(badge);
    flowLabel(entry).forEach((line,index)=>{
      const text=svgEl('text',{x:'9',y:String(31+index*13),class:index?'flow-line':'flow-line flow-title'});
      text.textContent=line.length>32?`${line.slice(0,31)}…`:line;group.append(text);
    });
    const title=svgEl('title');
    title.textContent=[`${node.node_type} at t=${node.time}`,
      node.acting_agent?`agent: ${node.acting_agent}`:'',
      node.selected_action?`action: ${node.selected_action.name}`:'',
      node.branch_role?`branch role: ${node.branch_role}`:'',
      node.decision_rationale||'',
      node.status==='pruned'?`pruned by ${node.pruning_policy||'policy'}: ${node.pruning_reason||''}`:''].filter(Boolean).join('\n');
    group.append(title);
    const scenario=scenarioByNode.get(node.node_id);
    if(scenario){
      group.classList.add('clickable');
      const action=svgEl('text',{x:'9',y:String(H-6),class:'flow-cta'});
      action.textContent=`inspect ${scenario.scenario_id}`;group.append(action);
      group.addEventListener('click',()=>selectScenario(scenario));
    }
    svgRoot.append(group);
  });
  box.append(scrollBox(svgRoot));
  const legend=document.createElement('div');legend.className='legend';
  [['flow-decision','decision (model-selected)'],['flow-counterfactual','decision (counterfactual branch)'],
   ['flow-event','event / transition'],['flow-terminal','terminal scenario'],['flow-pruned','pruned branch']]
    .forEach(([className,label])=>{const item=document.createElement('span');item.className='legend-item';
      const swatch=document.createElement('i');swatch.className=`swatch ${className}`;item.append(swatch,document.createTextNode(label));legend.append(item);});
  box.append(legend);
  if(truncated)box.append(note(`The tree has more than ${MAX_FLOW_NODES} nodes; the flowchart shows the first ${MAX_FLOW_NODES} in depth-first order. The full tree is available in the text view below.`,'assumption-note'));
  box.append(note('Every box is a recorded simulation node. Nothing is inferred or drawn from a template diagram.'));
}

/* ---------- variable time series ---------- */
function numericSeriesNames(scenarios,initial){
  const numeric=new Set();
  scenarios.forEach(scenario=>scenario.snapshots.forEach(snap=>Object.entries(snap.variables||{}).forEach(([key,value])=>{
    if(typeof value==='number'&&!Array.isArray(value))numeric.add(key);
    else if(typeof initial[key]==='number')numeric.add(key);})));
  return [...numeric].filter(name=>scenarios.some(scenario=>scenario.snapshots.some(snap=>typeof snap.variables?.[name]==='number')));
}
function storedHistoryChart(summary,scenarios){
  const history=summary&&summary.product_history;
  if(!history)return null;
  if(history.missing)return note(`The definition points at product history '${history.history_id}', but that series is not in histories/, so no historical forecast was fitted against it.`,'assumption-note');
  /* The projection is keyed by the history's own name, so it can never be mistaken for a
     variable this run recorded — the two lines are drawn and labelled separately. */
  const name=history.name;
  const projected=(scenarios||[]).map(scenario=>scenario.forecast?.projections?.[name]||[])
    .find(values=>values.length)||[];
  /* A definition can keep a history reference while a different forecast model runs, so a
     series this run never fitted is not drawn: the chart would show data nothing used. */
  if(!projected.length)return null;
  const series={scenario_id:'stored-history',name:`${history.name} (stored history)`,
    snapshots:(history.values||[]).map((value,index)=>({time:index,variables:{[name]:value}})),
    forecast:{projections:{[name]:projected}}};
  const recorded=(history.values||[]).length;
  const fittedFrom=Number(summary.time_horizon??recorded-1)+1;
  const projectionStart=fittedFrom>=recorded?fittedFrom:recorded;
  const section=seriesChart(name,[series],{},'recorded','projected past the recorded history',projectionStart);
  section.append(note(`These ${recorded} points are the stored history${history.source?` (${history.source})`:''}, graded ${String(history.evidence_grade||'unspecified').replaceAll('_',' ')} — this run did not produce them.`
    +` The dashed line continues their least-squares fit from t${projectionStart}; it is an extrapolation, not a measurement.`
    +(fittedFrom<recorded?` The recorded series runs past this run's ${summary.time_horizon}-step horizon, so the projection is drawn immediately after the recorded periods.`:'')));
  return section;
}
function referenceAnalogueChart(summary,scenarios){
  const item=summary&&summary.reference_history;
  if(!item)return null;
  if(item.missing)return note(`The definition points at reference history '${item.history_id}', but that series is not in histories/, so no analogue could be scaled.`,'assumption-note');
  const name=item.name;
  const projected=(scenarios||[]).map(scenario=>scenario.forecast?.projections?.[name]||[])
    .find(values=>values.length)||[];
  /* Only drawn when this run's forecast actually used the reference: a definition can
     keep a reference selection while a different model runs. */
  if(!projected.length)return null;
  /* The scaled series is what the model fitted, so the solid line is the borrowed shape
     after rescaling rather than the raw recorded numbers. */
  const values=(item.scaled_values&&item.scaled_values.length)?item.scaled_values:(item.values||[]);
  const series={scenario_id:'reference-analogue',name:`${name} (reference, rescaled)`,
    snapshots:values.map((value,index)=>({time:index,variables:{[name]:value}})),
    forecast:{projections:{[name]:projected}}};
  const recorded=values.length;
  const fittedFrom=Number(summary.time_horizon??recorded-1)+1;
  const projectionStart=fittedFrom>=recorded?fittedFrom:recorded;
  const section=seriesChart(name,[series],{},'recorded analogue','projected past the recorded analogue',projectionStart);
  const scale=item.scale;
  const rescaled=scale==null
    ?`This line is another product's recorded series, shown unscaled because no peak value was entered.`
    :`This line is another product's recorded series multiplied by ${fmt(scale)}, so its own peak of `
     +`${fmt(Math.max(...(item.values||[0])))} lands on the ${fmt(item.peak)} you entered.`;
  section.append(note(rescaled
    +` The ramp shape comes from ${recorded} recorded periods graded ${String(item.evidence_grade||'unspecified').replaceAll('_',' ')}`
    +(item.source?` (${item.source})`:'')+'; the peak level is an assumption you typed, not a measurement. '
    +'The dashed line continues the least-squares fit of the rescaled series; it is an extrapolation, not a second product\'s actual sales.'));
  return section;
}
function drawTimeSeries(scenarios,definition,summary){
  const box=byId('timeseries');box.replaceChildren();box.classList.remove('muted');
  const withSnapshots=(scenarios||[]).filter(scenario=>(scenario.snapshots||[]).length);
  const initial=definition?.initial_world_state?.variables||{};
  const names=withSnapshots.length?numericSeriesNames(withSnapshots,initial):[];
  const CAP=8;
  /* Variables the forecast actually projects are the informative ones, so they get the
     chart slots before variables that only sit still across the run. */
  const projectedName=name=>(scenarios||[]).some(scenario=>(scenario.forecast?.projections||{})[name]);
  const shown=[...names].sort((a,b)=>Number(projectedName(b))-Number(projectedName(a))).slice(0,CAP);
  shown.forEach(name=>box.append(seriesChart(name,withSnapshots,initial)));
  if(names.length>CAP)box.append(note(`Showing ${CAP} of ${names.length} numeric variables: projected series first, then the rest. All of them are listed in the scenario detail panel.`));
  const history=storedHistoryChart(summary,scenarios);
  if(history)box.append(history);
  const analogue=referenceAnalogueChart(summary,scenarios);
  if(analogue)box.append(analogue);
  if(!box.children.length){
    box.textContent=withSnapshots.length?'No numeric world variables were recorded across time steps.'
      :'No per-step state snapshots were recorded for this run.';
    return;}
  if(withSnapshots.length){
    /* Only a projection that continues a recorded world variable belongs in this caption.
       The stored history is captioned on its own chart, from its own data. */
    const worldProjected=shown.some(name=>(scenarios||[]).some(scenario=>(scenario.forecast?.projections||{})[name]));
    box.append(note(worldProjected
      ?'Solid lines are the recorded world state after each time step; t0 is the configured initial state. Dashed lines continue the fitted straight line past the simulated horizon — an extrapolation of the trend this run produced, not a measurement.'
      :'Each line is one retained scenario. Points are the recorded world state after each time step; t0 is the configured initial state.','assumption-note'));
  }
}
/* One line-drawing implementation for every chart in the app: run scenarios, stored histories,
   analogues, driver indexes and the standalone forecasters. It draws recorded points, a fitted
   model line, and a projected continuation, and it is interactive: legend entries toggle series,
   hovering a point reports the period, series, value and unit, and clicking one reports it to the
   caller so a panel can reveal that period's own detail. Nothing is interpolated between recorded
   points — a line segment only joins periods the model actually produced. */
function seriesChart(name,scenarios,initial,horizonWord='simulated',caption='projected past the simulated horizon',projectionStart=null,options={}){
  const W=560,H=250,PAD_L=58,PAD_R=14,PAD_T=16,PAD_B=30;
  const unit=options.unit||'';
  const periodWord=options.periodWord||'period';
  const section=document.createElement('section');section.className='metric-chart';
  const heading=document.createElement('h3');
  heading.textContent=unit?`${name.replaceAll('_',' ')} — ${unit}`:name.replaceAll('_',' ');
  section.append(heading);
  const lines=[];
  scenarios.forEach((scenario,index)=>{
    const start=typeof initial[name]==='number'?[{time:0,value:initial[name]}]:[];
    const points=[...start,...(scenario.snapshots||[]).filter(snap=>typeof snap.variables?.[name]==='number')
      .map(snap=>({time:snap.time,value:snap.variables[name]}))];
    const values=(scenario.forecast?.projections||{})[name]||[];
    // One recorded point is nothing to draw on its own, but it is the anchor a projection continues
    // from — a compound driver index is exactly that: one entered level, then geometric periods.
    if(points.length<2&&!values.length)return;
    const at=projectionStart??points[points.length-1].time+1;
    lines.push({key:`scenario:${scenario.scenario_id||index}`,name:scenario.name,scenario,
      note:scenario.chartNote||null,
      color:seriesColor(index),points,projected:values.map((value,step)=>({time:at+step,value}))});
  });
  (options.fitted||[]).forEach((item,index)=>{
    if((item.points||[]).length<2)return;
    lines.push({key:item.key||`fitted:${index}`,name:item.name||'Fitted trend',style:'fitted',
      note:item.note||null,
      color:item.color||seriesColor(index),points:item.points,projected:[]});
  });
  if(!lines.length){
    section.classList.add('is-empty');
    section.append(note(options.emptyNote||'This variable was not numeric in the recorded snapshots.'));
    return section;
  }
  const periods=Math.max(0,...lines.map(line=>line.projected.length));
  // A declared level, e.g. the target peak a user entered, drawn across the chart so the projected
  // line can be seen reaching or passing it. It is an assumption, so it never looks like a series.
  const marks=(options.valueLines||[]).filter(item=>Number.isFinite(Number(item.value)));
  const hidden=new Set();
  let selected=null;
  const holder=document.createElement('div');
  const tip=document.createElement('div');tip.className='chart-tip';tip.setAttribute('aria-hidden','true');
  section.append(holder,tip);

  function pointInfo(line,point,isProjected){
    return {name:line.name,scenario_id:line.scenario?.scenario_id||null,time:point.time,value:point.value,
      projected:isProjected,unit,periodWord};
  }
  function showTip(circle,line,point,isProjected){
    const info=pointInfo(line,point,isProjected);
    tip.replaceChildren();
    tip.append(Object.assign(document.createElement('b'),{textContent:line.name}));
    tip.append(document.createTextNode(`t${point.time}: ${fmt(point.value)}${unit?` ${unit}`:''}`));
    tip.append(Object.assign(document.createElement('span'),
      {textContent:isProjected?(options.projectedNote||'Projected value — not observed')
        :line.note||(line.style==='fitted'?'Fitted value — a model line, not an observation':'Recorded value')}));
    const box=holder.getBoundingClientRect(),frame=section.getBoundingClientRect();
    const scale=box.width/W;
    const left=Math.min(Math.max(6,box.left-frame.left+Number(circle.getAttribute('cx'))*scale-40),
      Math.max(6,frame.width-190));
    tip.style.left=`${left}px`;
    tip.style.top=`${Math.max(6,box.top-frame.top+Number(circle.getAttribute('cy'))*scale-58)}px`;
    tip.classList.add('is-on');
  }
  function hideTip(){tip.classList.remove('is-on');}

  function draw(){
    holder.replaceChildren();hideTip();
    const shown=lines.filter(line=>!hidden.has(line.key));
    const all=shown.flatMap(line=>[...line.points,...line.projected]);
    const axis=document.createElement('div');
    if(!shown.length){
      axis.className='muted';axis.textContent='Every series is hidden — choose a legend entry to show it again.';
      holder.append(axis);drawLegend();return;
    }
    const times=shown.flatMap(line=>line.points.map(point=>point.time));
    const values=[...shown.flatMap(line=>[...line.points,...line.projected].map(point=>point.value)),
      ...marks.map(item=>Number(item.value))];
    const minT=Math.min(...times),maxT=Math.max(...times);
    const maxProjected=Math.max(maxT,...shown.flatMap(line=>line.projected.map(point=>point.time)));
    let minV=Math.min(...values),maxV=Math.max(...values);
    if(minV===maxV){minV-=1;maxV+=1;}
    const spanT=Math.max(maxProjected-minT,1),spanV=maxV-minV;
    const x=time=>PAD_L+(time-minT)/spanT*(W-PAD_L-PAD_R);
    const y=value=>H-PAD_B-(value-minV)/spanV*(H-PAD_T-PAD_B);
    const svgRoot=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,width:'100%',class:'series-svg',role:'img',
      'aria-label':`Time series for ${name}${unit?` in ${unit}`:''}. The table above lists every value.`});
    svgRoot.append(svgEl('line',{x1:PAD_L,y1:H-PAD_B,x2:W-PAD_R,y2:H-PAD_B,class:'axis'}));
    svgRoot.append(svgEl('line',{x1:PAD_L,y1:PAD_T,x2:PAD_L,y2:H-PAD_B,class:'axis'}));
    [maxV,(minV+maxV)/2,minV].forEach(value=>{
      const label=svgEl('text',{x:String(PAD_L-6),y:String(y(value)+3),class:'axis-label','text-anchor':'end'});
      label.textContent=fmt(value);svgRoot.append(label);
      svgRoot.append(svgEl('line',{x1:PAD_L,y1:y(value),x2:W-PAD_R,y2:y(value),class:'grid'}));});
    for(let time=minT;time<=maxProjected;time++){
      const label=svgEl('text',{x:String(x(time)),y:String(H-8),class:`axis-label${time>maxT?' is-projected':''}`,
        'text-anchor':'middle'});
      label.textContent=`t${time}`;svgRoot.append(label);}
    (options.annotations||[]).forEach(item=>{
      if(item.time<minT||item.time>maxProjected)return;
      svgRoot.append(svgEl('line',{x1:x(item.time),y1:PAD_T,x2:x(item.time),y2:H-PAD_B,class:'marker'}));
      const text=svgEl('text',{x:String(x(item.time)+4),y:String(H-PAD_B-6),class:'marker-label'});
      text.textContent=item.label;svgRoot.append(text);});
    if(periods){
      svgRoot.append(svgEl('line',{x1:x(maxT),y1:PAD_T,x2:x(maxT),y2:H-PAD_B,class:'horizon'}));
      const marker=svgEl('text',{x:String(x(maxT)-4),y:String(PAD_T+9),class:'horizon-label','text-anchor':'end'});
      marker.textContent=horizonWord;svgRoot.append(marker);}
    const hits=[];
    shown.forEach(line=>{
      const klass=line.style==='fitted'?'fitted':null;
      const path=svgEl('path',{d:`M ${line.points.map(point=>`${x(point.time)},${y(point.value)}`).join(' L ')}`,
        fill:'none',stroke:line.color,'stroke-width':'2','stroke-linejoin':'round',class:klass||undefined});
      svgRoot.append(path);
      if(klass)line.points.forEach(point=>hits.push({line,point,projected:false}));
      else line.points.forEach(point=>{
        svgRoot.append(svgEl('circle',{cx:x(point.time),cy:y(point.value),r:'2.6',fill:line.color}));
        hits.push({line,point,projected:false});});
      if(!line.projected.length)return;
      const last=line.points[line.points.length-1];
      /* Only bridge to the recorded line when the projection really starts on the next period;
         otherwise the gap between the history and the horizon stays on screen. */
      const points=(line.projected[0].time===last.time+1?[last]:[]).concat(line.projected);
      svgRoot.append(svgEl('path',{class:'projection',d:`M ${points.map(point=>`${x(point.time)},${y(point.value)}`).join(' L ')}`,
        fill:'none',stroke:line.color,'stroke-width':'2','stroke-linejoin':'round'}));
      line.projected.forEach(point=>{
        svgRoot.append(svgEl('circle',{cx:x(point.time),cy:y(point.value),r:'2.6',
          fill:'var(--surface)',stroke:line.color,'stroke-width':'1.4'}));
        hits.push({line,point,projected:true});});
    });
    marks.forEach(item=>{
      const value=Number(item.value);
      svgRoot.append(svgEl('line',{x1:PAD_L,y1:y(value),x2:W-PAD_R,y2:y(value),class:'value-line'}));
      const label=svgEl('text',{x:String(W-PAD_R-2),y:String(y(value)-4),class:'value-label','text-anchor':'end'});
      label.textContent=item.label?`${item.label} ${fmt(value)}`:fmt(value);svgRoot.append(label);});
    hits.forEach(item=>{
      const circle=svgEl('circle',{cx:x(item.point.time),cy:y(item.point.value),r:'8',class:'chart-hit'});
      if(selected&&selected.time===item.point.time&&selected.name===item.line.name)circle.classList.add('is-active');
      circle.addEventListener('pointerenter',()=>showTip(circle,item.line,item.point,item.projected));
      circle.addEventListener('pointerleave',hideTip);
      circle.addEventListener('click',()=>{
        selected=item.projected?null:{time:item.point.time,name:item.line.name};
        draw();
        if(options.onSelect)options.onSelect(pointInfo(item.line,item.point,item.projected));});
      svgRoot.append(circle);});
    holder.append(svgRoot);
    heading.querySelectorAll('.chart-style').forEach(node=>node.remove());
    if(periods){const styleNote=document.createElement('span');styleNote.className='chart-style';
      styleNote.textContent=` · dashed = ${caption}`;heading.append(styleNote);}
    drawLegend();
  }

  function drawLegend(){
    const legend=holder.querySelector('.legend')||document.createElement('div');
    legend.className='legend';legend.replaceChildren();
    /* A scenario id is a key, not a name. It earns its place in a run comparison, where the reader
       must map a line back to the scenario table; a standalone panel sets scenarioKeys:false
       because its lines are already named. */
    const showKeys=options.scenarioKeys!==false;
    lines.forEach(line=>{
      const entry=document.createElement('button');
      entry.type='button';entry.className='legend-item';
      entry.setAttribute('aria-pressed',hidden.has(line.key)?'false':'true');
      if(hidden.has(line.key))entry.classList.add('is-off');
      entry.title=line.scenario?line.scenario.name:line.name;
      const swatch=document.createElement('i');swatch.className='swatch-dot';
      swatch.style.background=line.color;
      if(line.style==='fitted')swatch.classList.add('swatch-ring');
      const label=`${showKeys&&line.scenario?`${line.scenario.scenario_id}: `:''}${shortName(line.scenario||{name:line.name})}`;
      /* The suffix says the line is a model line, not a record — a name that already says
         "fitted" needs no second one, which used to print "Fitted trend line (fitted line)". */
      entry.append(swatch,document.createTextNode(
        line.style==='fitted'&&!/fitted/i.test(label)?`${label} (fitted line)`:label));
      entry.onclick=()=>{hidden.has(line.key)?hidden.delete(line.key):hidden.add(line.key);draw();};
      legend.append(entry);});
    holder.append(legend);
  }

  draw();
  section.chartLines=lines;
  return section;
}

/* ---------- external driver effects ---------- */
function drawDriverEffects(results){
  const box=byId('driverEffects');box.replaceChildren();box.classList.remove('muted');
  const impacts=results.driver_impacts||[],hypotheses=results.driver_hypotheses||[];
  if(!impacts.length&&!hypotheses.length){
    box.textContent='This run had no active external drivers, so no environment effects were applied.';box.classList.add('muted');return;}
  const grades=results.driver_evidence_grades||{};
  const byDriver=new Map();
  impacts.forEach(record=>{if(!byDriver.has(record.driver_id))byDriver.set(record.driver_id,[]);byDriver.get(record.driver_id).push(record);});
  [...byDriver.entries()].forEach(([driverId,records])=>{
    const section=document.createElement('div');section.className='assumption-group';
    const heading=document.createElement('b');
    heading.textContent=`${records[0].driver_name} — variant “${records[0].variant_id}” · ${records.length} applied effect${records.length===1?'':'s'}`;
    section.append(heading);section.append(gradeBadge(grades[driverId]||records[0].evidence_grade));
    section.append(tableFrom(['Source t','Effect t','Lag','Pathway','Target variable','Op','Configured','Applied','Level','Clamped'],
      records.map(record=>[`t${record.source_time}`,`t${record.effect_time}`,record.lag?`+${record.lag}`:'0',
        record.pathway,record.target_variable.replaceAll('_',' '),record.operation,fmt(record.configured_value),fmt(record.applied_value),
        fmt(record.level),record.bounded?'yes':'no'])));
    const basis=[...new Set(records.map(record=>record.basis).filter(Boolean))];
    basis.forEach(text=>section.append(note(text)));
    box.append(section);
  });
  if(hypotheses.length){
    const section=document.createElement('div');section.className='assumption-group hypothesis-group';
    const heading=document.createElement('b');heading.textContent=`Qualitative hypotheses — recorded, never applied (${hypotheses.length})`;section.append(heading);
    section.append(tableFrom(['Driver','Target variable','Direction','Grade','Status','Why it is not a number'],
      hypotheses.map(record=>[record.driver_name,record.target_variable.replaceAll('_',' '),record.operation,
        gradeBadge(record.evidence_grade),record.status,record.uncertainty||'No defensible estimate configured.'])));
    section.append(note('These pathways were deliberately not converted into state changes. They are reported so the gap is visible rather than silently quantified.','assumption-note'));
    box.append(section);
  }
  box.append(note('“Configured” is the authored value; “Applied” is what the engine wrote after variant scaling and bounds. A clamped effect means the configured strength exceeded a configured bound.'));
}

/* ---------- decision audit ---------- */
function drawDecisionAudit(scenarios){
  const table=byId('decisionAudit'),head=table.querySelector('thead'),body=table.querySelector('tbody');
  head.replaceChildren();body.replaceChildren();
  const summary=byId('decisionAuditSummary');summary.replaceChildren();
  const empty=byId('decisionAuditEmpty');
  const decisions=(scenarios||[]).flatMap(scenario=>(scenario.decision_trace||[])
    .filter(item=>item.event_type==='decision')
    .map(item=>({scenario,...item})));
  if(!decisions.length){empty.textContent='No decisions were recorded in this run.';empty.classList.remove('muted');return;}
  empty.textContent='';empty.classList.add('muted');
  const counts={};decisions.forEach(item=>{counts[item.decision_source||'unspecified']=(counts[item.decision_source||'unspecified']||0)+1;});
  Object.entries(counts).forEach(([source,count])=>{
    const item=document.createElement('span');item.className='legend-item';item.title=DECISION_SOURCE_HELP[source]||'';
    const swatch=document.createElement('i');swatch.className=`swatch source-${source}`;
    item.append(swatch,document.createTextNode(`${source.replaceAll('_',' ')}: ${count}`));summary.append(item);});
  ['Scenario','t','Agent','Action','Decision source','Score margin','Branch role','Why'].forEach(text=>{
    const th=document.createElement('th');th.textContent=text;head.append(th);});
  decisions.forEach(item=>{
    const tr=document.createElement('tr');
    const scenarioCell=document.createElement('td');const button=document.createElement('button');
    button.className='subtle';button.textContent=item.scenario.scenario_id;button.onclick=()=>selectScenario(item.scenario);
    scenarioCell.append(button);tr.append(scenarioCell);
    [item.time,item.agent_id,item.action?.name||'(none)'].forEach(value=>{const td=document.createElement('td');td.textContent=value??'—';tr.append(td);});
    const sourceCell=document.createElement('td');sourceCell.append(gradeBadgeSource(item.decision_source));tr.append(sourceCell);
    const marginCell=document.createElement('td');marginCell.textContent=item.objective_score_margin==null?'—':Number(item.objective_score_margin).toExponential(2);tr.append(marginCell);
    const roleCell=document.createElement('td');const role=document.createElement('span');
    role.className=item.branch_role==='counterfactual'?'grade grade-counterfactual':'grade grade-selected';
    role.textContent=item.branch_role||'selected';roleCell.append(role);tr.append(roleCell);
    const whyCell=document.createElement('td');whyCell.className='why';
    whyCell.textContent=item.rationale||item.alternative_reason||'';
    whyCell.title=decisionTooltip(item);
    tr.append(whyCell);body.append(tr);
  });
}
function decisionTooltip(item){
  const audit=item.llm_audit||{};
  const lines=[item.rationale,item.decision_context?.decision_reason,item.validity_reason];
  if(audit.provider)lines.push(`provider: ${audit.provider} / ${audit.model||'unknown'}`);
  if(audit.skip_reason)lines.push(`no provider call: ${audit.skip_reason}`);
  else if(audit.latency_ms!=null)lines.push(`latency: ${Number(audit.latency_ms).toFixed(0)} ms over ${audit.provider_attempts||1} attempt(s)`);
  const tokens=audit.token_usage||{};
  if(tokens.total_tokens!=null)lines.push(`tokens: ${tokens.total_tokens} (prompt ${tokens.prompt_tokens??0} / completion ${tokens.completion_tokens??0})`);
  return lines.filter(Boolean).join('\n');
}
function gradeBadgeSource(source){
  const span=document.createElement('span');span.className=`grade source-${source||'unspecified'}`;
  span.textContent=(source||'unspecified').replaceAll('_',' ');
  span.title=DECISION_SOURCE_HELP[source]||'No decision source was recorded.';return span;
}

/* ---------- driver variant comparison ---------- */
function variantMetricKeys(runs){
  const keys=new Set();
  runs.forEach(run=>(run.result.scenarios||[]).forEach(scenario=>Object.entries(scenario.forecast?.metrics||{}).forEach(([key,value])=>{
    if(typeof value==='number')keys.add(key);})));
  return [...keys].filter(key=>key!=='time');
}
function renderVariantComparison(driver,runs){
  const box=byId('variantComparison');box.replaceChildren();box.classList.remove('muted');
  const heading=document.createElement('h3');heading.textContent=`${driver.name} — ${runs.length} variants, one run each`;box.append(heading);
  box.append(note('Same definition, same agents, same rules. Only the driver trajectory changed. Preview runs are not saved to disk.','assumption-note'));
  const keys=variantMetricKeys(runs);
  if(!keys.length){box.append(note('These runs produced no numeric forecast metrics to compare.'));return;}
  const label=document.createElement('label');label.className='agent-field';label.append(document.createTextNode('Chart metric'));
  const select=document.createElement('select');
  keys.forEach(key=>select.add(new Option(key.replaceAll('_',' '),key)));
  label.append(select);box.append(label);
  const chart=document.createElement('div');chart.className='charts';box.append(chart);
  const drawChart=()=>{
    chart.replaceChildren();const key=select.value;
    const rows=[];
    runs.forEach(run=>(run.result.scenarios||[]).forEach(scenario=>rows.push({
      label:`${run.variant.label||run.variant.variant_id} · ${scenario.scenario_id}`,
      value:Number(scenario.forecast?.metrics?.[key]||0)})));
    const max=Math.max(...rows.map(row=>Math.abs(row.value)),0);
    const section=document.createElement('section');section.className='metric-chart';
    const title=document.createElement('h3');title.textContent=key.replaceAll('_',' ');section.append(title);
    rows.forEach(row=>{
      const line=document.createElement('div');line.className='bar-row';
      const name=document.createElement('span');name.className='bar-label';name.textContent=row.label;name.title=row.label;
      const track=document.createElement('div');track.className='bar-track';
      const fill=document.createElement('div');fill.className='bar-fill';fill.style.width=max>0?`${Math.abs(row.value)/max*100}%`:'0%';
      track.append(fill);const value=document.createElement('strong');value.textContent=fmt(row.value);
      line.append(name,track,value);section.append(line);});
    chart.append(section);
  };
  select.onchange=drawChart;drawChart();
  const headers=['Variant','Grade','Scenarios','Pruned','Duration (s)',...keys.map(key=>key.replaceAll('_',' '))];
  const rows=runs.flatMap(run=>(run.result.scenarios||[]).map((scenario,index)=>{
    const label=run.variant.label||run.variant.variant_id;
    const summaryRow=[index?`↳ ${label}`:label,
      index?'':gradeBadge(run.variant.evidence_grade||driver.evidence_grade),
      index?'':(run.result.summary?.terminal_scenarios??'—'),
      index?'':(run.result.summary?.pruned_nodes??'—'),
      index?'':Number(run.result.summary?.duration_seconds||0).toFixed(3)];
    return [...summaryRow,...keys.map(key=>fmt(scenario.forecast?.metrics?.[key]))];
  }));
  box.append(tableFrom(headers,rows));
  const spread=keys.map(key=>{
    const values=runs.flatMap(run=>(run.result.scenarios||[]).map(scenario=>Number(scenario.forecast?.metrics?.[key]||0)));
    return {key,min:Math.min(...values),max:Math.max(...values)};
  }).filter(item=>item.max!==item.min);
  if(spread.length){
    const section=document.createElement('div');section.className='assumption-group';
    const spreadHeading=document.createElement('b');spreadHeading.textContent='Where the variants actually differ';section.append(spreadHeading);
    section.append(tableFrom(['Variable','Lowest across variants','Highest across variants'],
      spread.map(item=>[item.key.replaceAll('_',' '),fmt(item.min),fmt(item.max)])));
    box.append(section);
  }else{box.append(note('All variants produced identical metrics. Either the driver has no configured pathway to these metrics, or every pathway was clamped or qualitative-only.'));}
  box.append(note('Differences between variants are consequences of the configured assumptions. A larger number is not a better or more likely outcome.','assumption-note'));
}
