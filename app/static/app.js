const byId = id => document.getElementById(id);
const agentBox = byId('agents'), actionBox = byId('actions'), triggerBox = byId('triggers'), driverBox = byId('drivers');
let currentId = null, saved = false, resultScenarios = [], nodeIndex = {}, currentEvidence = [], currentAgents = [], currentDrivers = [];
// Fields the guided forms do not edit (evaluation objectives, clinical and
// affordability assumptions, domain, transient variables). Kept so that saving
// from the UI never silently drops configuration it has no control for.
let currentDefinition = null;

function setStatus(text, bad=false){byId('status').textContent=text;byId('status').style.color=bad?'#a2352d':'#58706e';}
function parseBox(id, fallback){try{return JSON.parse(byId(id).value||JSON.stringify(fallback));}catch(e){throw new Error(`${id}: ${e.message}`);}}
function typedValue(value,type){if(type==='number')return Number(value);if(type==='boolean')return value==='true';if(type==='object'){try{return JSON.parse(value);}catch{return value;}}return value;}
function addVariableRow(name='',value='',meta={}){
  const tr=document.createElement('tr');tr._meta=meta||{};
  const types=['number','string','boolean','object'];let type=meta.type|| (typeof value==='number'?'number':typeof value==='boolean'?'boolean':typeof value==='object'?'object':'string');
  const cells=[document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td'),document.createElement('td')];
  const nameInput=document.createElement('input');nameInput.value=name;nameInput.placeholder='variable_name';
  const typeSelect=document.createElement('select');types.forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;if(t===type)o.selected=true;typeSelect.append(o)});
  const valueInput=document.createElement('input');valueInput.value=typeof value==='object'?JSON.stringify(value):String(value);valueInput.placeholder='value';
  const minInput=document.createElement('input');minInput.value=meta.min??'';minInput.placeholder='optional';
  const maxInput=document.createElement('input');maxInput.value=meta.max??'';maxInput.placeholder='optional';
  const descInput=document.createElement('input');descInput.value=meta.description||'';descInput.placeholder='optional';
  const remove=document.createElement('button');remove.className='remove-row';remove.textContent='Remove';remove.onclick=()=>tr.remove();
  [nameInput,typeSelect,valueInput,minInput,maxInput,descInput,remove].forEach((el,i)=>cells[i].append(el));
  if(meta.evidence_grade){const badge=document.createElement('span');badge.className=`grade grade-${meta.evidence_grade}`;badge.textContent=meta.evidence_grade.replaceAll('_',' ');badge.title=(meta.assumption_labels||[]).join(' ')||'Evidence grade recorded in the definition.';cells[5].append(badge);}
  cells.forEach(c=>tr.append(c));byId('variables').append(tr);
}
function worldVariableNames(){return [...byId('variables').rows].map(row=>row.querySelector('input')?.value.trim()).filter(Boolean);}
function availableActions(){try{return JSON.parse(actionBox.value||'[]');}catch{return [];}}
function control(labelText,element){const label=document.createElement('label');label.className='agent-field';label.append(document.createTextNode(labelText),element);return label;}
function renderAgents(agents){
  currentAgents=JSON.parse(JSON.stringify(agents||[]));const root=byId('agentsEditor');root.replaceChildren();
  const worldNames=worldVariableNames(), actions=availableActions();
  currentAgents.forEach((agent,index)=>{
    const card=document.createElement('article');card.className='agent-card';card.dataset.index=index;
    const top=document.createElement('div');top.className='agent-card-head';const title=document.createElement('h3');title.textContent=agent.name||agent.id;top.append(title);
    const remove=document.createElement('button');remove.type='button';remove.className='remove-row';remove.textContent='Remove agent';remove.onclick=()=>{currentAgents.splice(index,1);renderAgents(currentAgents);syncAgentsFromForm();};top.append(remove);card.append(top);
    const fields=document.createElement('div');fields.className='agent-fields';
    const id=document.createElement('input');id.value=agent.id||'';id.readOnly=true;id.title='Internal reference used by actions and triggers';fields.append(control('Internal ID',id));
    const name=document.createElement('input');name.value=agent.name||'';name.dataset.field='name';fields.append(control('Display name',name));
    const type=document.createElement('select');const roleOptions=['generic','company','competitor','payer','physician','patient'];if(agent.type&&!roleOptions.includes(agent.type))roleOptions.push(agent.type);roleOptions.forEach(value=>{const option=new Option(value.replaceAll('_',' '),value);option.selected=value===(agent.type||'generic');type.add(option);});type.dataset.field='type';fields.append(control('Stakeholder type',type));
    const objective=document.createElement('textarea');objective.value=agent.objective||'';objective.rows=2;objective.dataset.field='objective';fields.append(control('What is this agent trying to do?',objective));card.append(fields);
    const actionSection=document.createElement('fieldset');actionSection.className='choice-set';const actionLegend=document.createElement('legend');actionLegend.textContent='Choices this agent can make';actionSection.append(actionLegend);
    const ownActions=actions.filter(action=>action.agent_id===agent.id);
    if(!ownActions.length){const note=document.createElement('p');note.className='field-note';note.textContent='No actions are configured for this agent yet. Existing examples are ready to run; adding new actions is an advanced setup.';actionSection.append(note);}
    ownActions.forEach(action=>{const label=document.createElement('label');label.className='check-option';const input=document.createElement('input');input.type='checkbox';input.dataset.actionId=action.id;input.checked=(agent.available_actions||[]).includes(action.id);label.append(input,document.createTextNode(action.name||action.id));actionSection.append(label);});card.append(actionSection);
    const observationSection=document.createElement('fieldset');observationSection.className='choice-set';const observationLegend=document.createElement('legend');observationLegend.textContent='What this agent can observe';observationSection.append(observationLegend);
    const allLabel=document.createElement('label');allLabel.className='check-option';const allInput=document.createElement('input');allInput.type='checkbox';allInput.dataset.observeAll='true';allInput.checked=agent.observable_state==='all';allLabel.append(allInput,document.createTextNode('All world variables'));observationSection.append(allLabel);
    const selected=Array.isArray(agent.observable_state)?agent.observable_state:[];
    worldNames.forEach(variable=>{const label=document.createElement('label');label.className='check-option';const input=document.createElement('input');input.type='checkbox';input.dataset.observation=variable;input.checked=selected.includes(variable);input.disabled=allInput.checked;label.append(input,document.createTextNode(variable.replaceAll('_',' ')));observationSection.append(label);});
    allInput.addEventListener('change',()=>{observationSection.querySelectorAll('[data-observation]').forEach(item=>item.disabled=allInput.checked);});
    card.append(observationSection);card.addEventListener('input',syncAgentsFromForm);card.addEventListener('change',syncAgentsFromForm);root.append(card);
  });
}
function syncAgentsFromForm(){
  currentAgents=[...byId('agentsEditor').querySelectorAll('.agent-card')].map((card,index)=>{
    const agent=currentAgents[index]||{};const value=name=>card.querySelector(`[data-field="${name}"]`)?.value||'';
    agent.name=value('name');agent.type=value('type')||'generic';agent.objective=value('objective');const heading=card.querySelector('.agent-card-head h3');if(heading)heading.textContent=agent.name||agent.id;
    agent.available_actions=[...card.querySelectorAll('[data-action-id]:checked')].map(input=>input.dataset.actionId);
    const all=card.querySelector('[data-observe-all]')?.checked;
    agent.observable_state=all?'all':[...card.querySelectorAll('[data-observation]:checked')].map(input=>input.dataset.observation);
    agent.decision_policy=agent.decision_policy||{type:'rule_based',default_actions:[]};
    agent.decision_policy.default_actions=agent.available_actions.slice();return agent;
  });
  agentBox.value=JSON.stringify(currentAgents,null,2);
}
function loadTemplate(templateId){return request(`/simulations/templates/${encodeURIComponent(templateId)}`).then(definition=>{
  loadDefinition(definition,false);const suffix=String(Date.now()).slice(-6);byId('simId').value=`${definition.metadata.id}-copy-${suffix}`;byId('name').value=`${definition.metadata.name} (copy)`;currentId=null;saved=false;
  setStatus('Example loaded. It is labeled hypothetical; assumptions are illustrative.');
});}
function loadDefinition(d,isSaved=false){
  currentDefinition=JSON.parse(JSON.stringify(d||{}));
  currentEvidence=JSON.parse(JSON.stringify(d.evidence||[]));
  currentId=d.metadata.id; saved=isSaved;byId('simId').value=d.metadata.id;byId('name').value=d.metadata.name;byId('description').value=d.metadata.description||'';
  byId('horizon').value=d.settings.time_horizon;byId('step').value=d.settings.step_duration;byId('stepUnit').value=d.settings.step_unit;byId('decisionPolicy').value=d.settings.decision_policy||'rule_based';
  byId('forecast').value=d.forecast_model_id||'state_metrics';byId('policy').value=d.scenario_generation.policy;
  byId('limit').value=d.scenario_generation.max_scenarios??9;byId('safety').value=d.scenario_generation.safety_limit??1000;
  byId('variables').replaceChildren();const vars=d.initial_world_state.variables||{};const metadata=d.world_variable_metadata||{};
  Object.entries(vars).forEach(([k,v])=>addVariableRow(k,v,metadata[k]||{}));
  agentBox.value=JSON.stringify(d.agents||[],null,2);actionBox.value=JSON.stringify(d.action_definitions||[],null,2);renderAgents(d.agents||[]);
  driverBox.value=JSON.stringify(d.external_drivers||[],null,2);renderDrivers(d.external_drivers||[]);
  triggerBox.value=JSON.stringify(d.trigger_definitions||[],null,2);byId('transitions').value=JSON.stringify(d.transition_rules||[],null,2);
  byId('initialEvents').value=JSON.stringify(d.settings.initial_events||[],null,2);byId('scheduledEvents').value=JSON.stringify(d.settings.scheduled_events||[],null,2);
  byId('errors').textContent='';clearResults();showWorkspace();setStatus(isSaved?'Loaded saved simulation':'Template loaded');
}
function blankDefinition(){return {metadata:{id:'new-simulation',name:'New Simulation',description:'',domain:'general'},initial_world_state:{variables:{}},world_variable_metadata:{},evidence:[],agents:[],action_definitions:[],trigger_definitions:[],transition_rules:[],external_drivers:[],settings:{time_horizon:4,step_duration:1,step_unit:'round',decision_policy:'rule_based',initial_events:[{id:'start',time:0,event_type:'simulation_start',description:'Simulation begins'}],scheduled_events:[]},forecast_model_id:'state_metrics',scenario_generation:{policy:'diversity',max_scenarios:9,diversity_by_agents:[],safety_limit:1000}};}
function definitionFromForm(){
  const variables={}, variableMetadata={};
  [...byId('variables').rows].forEach(row=>{const [name,type,value,min,max,description]=[...row.querySelectorAll('input,select')];if(!name.value.trim())return;const key=name.value.trim();variables[key]=typedValue(value.value,type.value);
    const m={...(row._meta||{}),type:type.value};
    if(min.value!=='')m.min=Number(min.value);else delete m.min;
    if(max.value!=='')m.max=Number(max.value);else delete m.max;
    if(description.value)m.description=description.value;else delete m.description;
    variableMetadata[key]=m;});
  const id=byId('simId').value.trim();if(!id)throw new Error('Definition ID is required.');
  const base=JSON.parse(JSON.stringify(currentDefinition||blankDefinition()));
  const agents=parseBox('agents',[]);
  base.metadata={...(base.metadata||{}),id,name:byId('name').value.trim(),description:byId('description').value,domain:base.metadata?.domain||'general'};
  base.initial_world_state={...(base.initial_world_state||{}),time:base.initial_world_state?.time??0,variables};
  base.world_variable_metadata=variableMetadata;
  base.evidence=currentEvidence;
  base.agents=agents;base.action_definitions=parseBox('actions',[]);base.trigger_definitions=parseBox('triggers',[]);base.transition_rules=parseBox('transitions',[]);
  base.external_drivers=parseBox('drivers',[]);
  base.settings={...(base.settings||{}),time_horizon:Number(byId('horizon').value),step_duration:Number(byId('step').value),step_unit:byId('stepUnit').value,
    initial_events:parseBox('initialEvents',[]),scheduled_events:parseBox('scheduledEvents',[]),decision_policy:byId('decisionPolicy').value};
  base.forecast_model_id=byId('forecast').value||null;
  const previousDiversity=base.scenario_generation?.diversity_by_agents||[];
  base.scenario_generation={...(base.scenario_generation||{}),policy:byId('policy').value,max_scenarios:Number(byId('limit').value),
    diversity_by_agents:Array.isArray(previousDiversity)&&previousDiversity.length?previousDiversity:agents.map(agent=>agent.id),
    safety_limit:Number(byId('safety').value)};
  return base;
}
async function request(url,options={}){const response=await fetch(url,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});let data;try{data=await response.json();}catch{data={};}if(!response.ok){const detail=data.detail;throw new Error(typeof detail==='string'?detail:detail?.errors?.join('\n')||JSON.stringify(detail)||response.statusText);}return data;}
async function save(){const definition=definitionFromForm();if(saved&&currentId===definition.metadata.id){await request(`/simulations/${encodeURIComponent(currentId)}`,{method:'PUT',body:JSON.stringify(definition)});}else{await request('/simulations',{method:'POST',body:JSON.stringify(definition)});saved=true;currentId=definition.metadata.id;}loadDefinition(definition,true);await refreshSaved();setStatus('Saved to local JSON');return definition;}
async function refreshSaved(){const items=await request('/simulations');const select=byId('savedSelect');const keep=select.value;select.replaceChildren(new Option('Choose saved simulation…',''));items.forEach(item=>select.add(new Option(item.name,item.simulation_id)));if(items.some(item=>item.simulation_id===keep))select.value=keep;return items;}
async function refreshTemplates(){const items=await request('/simulations/templates');const select=byId('templateSelect');select.replaceChildren(new Option('Choose an example…',''));items.forEach(item=>{const option=new Option(item.name,item.id);option.title=item.description||'';select.add(option);});return items;}
function clearResults(){byId('summary').textContent='Run a simulation to view results.';byId('tree').textContent='The tree will appear here after a run.';byId('comparison').querySelector('thead').replaceChildren();byId('comparison').querySelector('tbody').replaceChildren();byId('scenarioDetail').textContent='Select a terminal scenario in the flowchart, tree, or comparison table.';byId('charts').textContent='Run a simulation to compare outcomes visually.';clearDashboard();resultScenarios=[];nodeIndex={};}
function safePre(title,value){const section=document.createElement('div');section.className='detail-block';const heading=document.createElement('b');heading.textContent=title;const pre=document.createElement('pre');pre.textContent=JSON.stringify(value,null,2);section.append(heading,pre);return section;}
function selectScenario(scenario){
  const target=byId('scenarioDetail');target.replaceChildren();const heading=document.createElement('h3');heading.textContent=scenario.name;target.append(heading);
  const lineage=[];let node=nodeIndex[scenario.terminal_node_id];while(node){lineage.push(node);node=node.parent_node_id?nodeIndex[node.parent_node_id]:null;}lineage.reverse();
  target.append(safePre('Complete lineage',lineage.map(n=>({node_id:n.node_id,node_type:n.node_type,status:n.status,event:n.triggering_event,agent:n.acting_agent,action:n.selected_action,state:n.world_state.variables}))));
  target.append(safePre('Actions taken',scenario.actions));target.append(safePre('Triggering events',scenario.decision_trace.filter(t=>t.event).map(t=>t.event)));
  target.append(safePre('World-state changes',scenario.decision_trace.filter(t=>Object.keys(t.state_changes||{}).length).map(t=>({time:t.time,type:t.event_type,changes:t.state_changes}))));
  target.append(safePre('Final state',scenario.final_state));target.append(safePre('Forecast',scenario.forecast));target.append(safePre('Decision trace',scenario.decision_trace));
}
function drawTree(root,scenarios){
  const tree=byId('tree');tree.replaceChildren();nodeIndex={};const walk=n=>{nodeIndex[n.node_id]=n;(n.children||[]).forEach(walk)};walk(root);
  const scenarioByNode=new Map(scenarios.map(s=>[s.terminal_node_id,s]));
  function addNode(node,parent){
    const details=document.createElement('details');details.open=node.node_type==='root'||node.node_type==='decision';
    const summary=document.createElement('summary');summary.className=node.status;
    let label=node.node_type==='root'?'ROOT':node.node_type==='decision'?`${node.acting_agent}: ${node.selected_action?.name||'decision'}`:node.node_type==='event'?`${node.triggering_event?.event_type||'event'}: ${node.triggering_event?.description||''}`:`Transition${node.triggering_event?.description?': '+node.triggering_event.description:''}`;
    if(node.status==='pruned')label+=` [PRUNED: ${node.pruning_reason||''}]`;if(node.status==='terminal')label+=' [TERMINAL]';summary.textContent=label;details.append(summary);
    const scenario=scenarioByNode.get(node.node_id);if(scenario){const btn=document.createElement('button');btn.textContent=`Inspect ${scenario.scenario_id}`;btn.onclick=()=>selectScenario(scenario);details.append(btn);}
    if(node.status==='pruned'&&node.pruning_policy){const p=document.createElement('small');p.textContent=`Policy: ${node.pruning_policy}; retained comparison: ${node.competing_retained_node_id||'none'}`;details.append(p);}
    (node.children||[]).forEach(child=>addNode(child,details));parent.append(details);
  }
  addNode(root,tree);
}
function drawComparison(scenarios){
  const table=byId('comparison'),head=table.querySelector('thead'),body=table.querySelector('tbody');head.replaceChildren();body.replaceChildren();
  const keys=[...new Set(scenarios.flatMap(s=>Object.keys(s.forecast?.metrics||{})))];const tr=document.createElement('tr');['Scenario',...keys].forEach(key=>{const th=document.createElement('th');th.textContent=key;tr.append(th)});head.append(tr);
  scenarios.forEach(s=>{const row=document.createElement('tr');const first=document.createElement('td');const btn=document.createElement('button');btn.className='subtle scenario-name';btn.textContent=s.name;btn.title=s.name;btn.onclick=()=>selectScenario(s);first.append(btn);
    const counterfactual=(s.decision_trace||[]).filter(t=>t.event_type==='decision'&&t.branch_role==='counterfactual').length;
    const role=document.createElement('span');role.className=counterfactual?'grade grade-counterfactual':'grade grade-selected';role.textContent=counterfactual?`${counterfactual} counterfactual choice${counterfactual===1?'':'s'}`:'model-selected path';first.append(role);
    row.append(first);keys.forEach(k=>{const td=document.createElement('td');td.textContent=s.forecast?.metrics?.[k]??'—';row.append(td)});body.append(row);});
}
function formatChartValue(metric,value){if(metric==='market_share')return `${(value*100).toFixed(2)}%`;if(metric==='patients_treated')return Math.round(value).toLocaleString();return Number(value).toLocaleString(undefined,{maximumFractionDigits:0})+' scenario currency';}
function drawCharts(scenarios){
  const root=byId('charts');root.replaceChildren();root.classList.remove('muted');
  const metrics=[['cumulative_sales','Cumulative modeled sales'],['peak_sales','Peak modeled sales'],['patients_treated','Patients treated (modeled)'],['market_share','Market share (modeled)']];
  const available=metrics.filter(([key])=>scenarios.some(s=>typeof s.forecast?.metrics?.[key]==='number'));
  if(!available.length){root.textContent='This forecast does not provide chartable metrics.';return;}
  available.forEach(([key,title])=>{
    const section=document.createElement('section');section.className='metric-chart';const heading=document.createElement('h3');heading.textContent=title;section.append(heading);
    const values=scenarios.map(s=>Number(s.forecast?.metrics?.[key]||0));const max=Math.max(...values,0);
    scenarios.forEach((scenario,index)=>{const row=document.createElement('div');row.className='bar-row';const label=document.createElement('span');label.className='bar-label';label.textContent=scenario.name;label.title=scenario.name;const track=document.createElement('div');track.className='bar-track';const bar=document.createElement('div');bar.className='bar-fill';bar.style.width=max>0?`${Math.max(0,values[index]/max*100)}%`:'0%';track.append(bar);const value=document.createElement('strong');value.textContent=formatChartValue(key,values[index]);row.append(label,track,value);section.append(row);});
    if(max===0&&(key==='cumulative_sales'||key==='patients_treated'||key==='market_share')){const note=document.createElement('p');note.className='zero-note';note.textContent='All scenarios are zero for this metric. Check that the definition includes a patient population and market-share dynamics; the smoke-test template intentionally omits those forecast inputs.';section.append(note);}
    root.append(section);
  });
  const note=document.createElement('p');note.className='assumption-note';note.textContent='Charts visualize the configured model only. Example values are synthetic and uncalibrated.';root.append(note);
}
async function runSimulation(){
  setProgress('Saving definition…',10);
  const definition=await save();
  const path=`/simulations/${encodeURIComponent(currentId)}`;
  setProgress('Validating definition…',25);
  await request(`${path}/validate`,{method:'POST'});
  setProgress('Running scenario tree…',55);
  const runInfo=await request(`${path}/run`,{method:'POST'});
  setProgress('Collecting traces and driver effects…',80);
  const results=await request(`${path}/results`);
  setProgress('Rendering charts, flowchart, and audit tables…',92);
  resultScenarios=results.scenarios;
  renderDashboard(results,definition);
  setProgress(`Run complete: ${runInfo.scenario_count} scenario${runInfo.scenario_count===1?'':'s'} in ${runInfo.duration_seconds.toFixed(3)}s`,100);
  setStatus(`Run complete: ${runInfo.scenario_count} scenarios`);
  setTimeout(hideProgress,2200);
}

byId('addVariable').onclick=()=>addVariableRow();
byId('addAgent').onclick=()=>{const number=currentAgents.length+1;let id=`new-agent-${number}`;while(currentAgents.some(agent=>agent.id===id))id=`new-agent-${Math.floor(Math.random()*100000)}`;currentAgents.push({id,name:`New agent ${number}`,type:'generic',objective:'Describe this stakeholder’s goal.',observable_state:[],available_actions:[],decision_policy:{type:'rule_based',default_actions:[]}});renderAgents(currentAgents);syncAgentsFromForm();};
actionBox.addEventListener('change',()=>renderAgents(currentAgents));
byId('variables').addEventListener('change',()=>renderAgents(currentAgents));
agentBox.addEventListener('change',()=>{try{renderAgents(JSON.parse(agentBox.value||'[]'));}catch(error){byId('errors').textContent=`Agent settings JSON: ${error.message}`;}});
driverBox.addEventListener('change',()=>{try{renderDrivers(JSON.parse(driverBox.value||'[]'));}catch(error){byId('errors').textContent=`Driver settings JSON: ${error.message}`;}});
byId('newBtn').onclick=()=>startBlank();
byId('saveBtn').onclick=async()=>{try{await save();byId('errors').textContent='';}catch(e){byId('errors').textContent=e.message;setStatus('Save failed',true);}};
byId('loadBtn').onclick=async()=>{try{const id=byId('savedSelect').value;if(!id)throw new Error('Choose a saved simulation first.');const data=await request(`/simulations/${encodeURIComponent(id)}`);loadDefinition(data.definition,true);}catch(e){byId('errors').textContent=e.message;setStatus('Load failed',true);}};
byId('templateLoadBtn').onclick=async()=>{try{const id=byId('templateSelect').value;if(!id)throw new Error('Choose an example first.');await loadTemplate(id);}catch(e){byId('errors').textContent=e.message;setStatus('Example load failed',true);}};
byId('validateBtn').onclick=async()=>{try{const d=definitionFromForm();const result=await request('/simulations/validate',{method:'POST',body:JSON.stringify(d)});byId('errors').textContent='';
  const gaps=[];if(!(d.agents||[]).length)gaps.push('no agents');if(!Object.keys(d.initial_world_state?.variables||{}).length)gaps.push('no world variables');if(!(d.action_definitions||[]).length)gaps.push('no actions');
  setStatus(!result.valid?'Validation failed':gaps.length?`Definition is valid, but it has ${gaps.join(', ')} — a run will only produce a baseline path.`:'Definition is valid — ready to run');
  }catch(e){byId('errors').textContent=e.message;setStatus('Validation failed',true);}};
byId('runBtn').onclick=async()=>{const button=byId('runBtn');button.disabled=true;try{byId('errors').textContent='';await runSimulation();}catch(e){byId('errors').textContent=e.message;hideProgress();setStatus('Run failed',true);}finally{button.disabled=false;}};
byId('duplicateBtn').onclick=async()=>{try{if(!saved)await save();const d=await request(`/simulations/${encodeURIComponent(currentId)}/duplicate`,{method:'POST'});await refreshSaved();const loaded=await request(`/simulations/${encodeURIComponent(d.simulation_id)}`);loadDefinition(loaded.definition,true);}catch(e){byId('errors').textContent=e.message;setStatus('Duplicate failed',true);}};
byId('savedSelect').onchange=async()=>{const id=byId('savedSelect').value;if(!id)return;try{const d=await request(`/simulations/${encodeURIComponent(id)}`);loadDefinition(d.definition,true);}catch(e){setStatus(e.message,true);}};
