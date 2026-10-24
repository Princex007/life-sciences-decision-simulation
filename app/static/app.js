const byId = id => document.getElementById(id);
const agentBox = byId('agents'), actionBox = byId('actions'), triggerBox = byId('triggers'), driverBox = byId('drivers');
let currentId = null, saved = false, resultScenarios = [], nodeIndex = {}, currentEvidence = [], currentAgents = [], currentDrivers = [];
let forecastModels = [], storedHistories = [];
let referenceRationale = '';
/* Why a catalogued model cannot run yet, in the terms the builder can act on. */
const REQUIREMENT_HELP = {
  external_drivers: 'Needs at least one enabled external driver with a quantitative pathway in step 6.',
  product_history: 'Needs a stored product history: import a CSV or Excel file (or paste the numbers) in the forecaster on the home page, save it, then pick it below.',
  reference_product: 'Needs a stored history of a DIFFERENT product and a positive peak value: import and save series in the forecaster on the home page, then pick the analogue below.'
};
// Fields the guided forms do not edit (evaluation objectives, clinical and
// affordability assumptions, domain, transient variables). Kept so that saving
// from the UI never silently drops configuration it has no control for.
let currentDefinition = null;

function setStatus(text, bad=false){const el=byId('status');el.textContent=text;el.classList.toggle('is-bad',bad);el.classList.toggle('is-ok',!bad);}
/* Discard deletes a file, so it is only offered when a file actually exists. */
function syncDiscardButton(){
  const btn=byId('discardBtn');if(!btn)return;
  const deletable=Boolean(saved&&currentId);
  btn.disabled=!deletable;
  const hint=btn.nextElementSibling;
  if(hint&&hint.classList.contains('hint'))hint.dataset.hint=deletable
    ?`Delete simulations/${currentId}.json and clear the editor. Asks before deleting; a deleted file is not recoverable.`
    :'Nothing to discard yet: this simulation has not been saved, so there is no file to delete. Use New to clear the form.';
}
function parseBox(id, fallback){try{return JSON.parse(byId(id).value||JSON.stringify(fallback));}catch(e){throw new Error(`${id}: ${e.message}`);}}
function typedValue(value,type){if(type==='number')return Number(value);if(type==='boolean')return value==='true';if(type==='object'){try{return JSON.parse(value);}catch{return value;}}return value;}
function optionalInt(id){const raw=byId(id).value.trim();if(raw==='')return null;const value=Number(raw);if(!Number.isInteger(value)||value<0)throw new Error(`${id}: enter a whole number of 0 or more, or leave it empty for no limit.`);return value;}
function addVariableRow(name='',value='',meta={}){
  const tr=document.createElement('tr');tr._meta=meta||{};
  const types=['number','string','boolean','object'];let type=meta.type|| (typeof value==='number'?'number':typeof value==='boolean'?'boolean':typeof value==='object'?'object':'string');
  const nameInput=document.createElement('input');nameInput.value=name;nameInput.placeholder='variable_name';
  const typeSelect=document.createElement('select');types.forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=t;if(t===type)o.selected=true;typeSelect.append(o)});
  let typeTouched=false;typeSelect.addEventListener('change',()=>{typeTouched=true;});
  const valueInput=document.createElement('input');valueInput.value=typeof value==='object'?JSON.stringify(value):String(value);valueInput.placeholder='value';
  valueInput.addEventListener('change',()=>{
    if(typeTouched)return;
    const raw=valueInput.value.trim();
    if(/^-?\d+(\.\d+)?$/.test(raw))typeSelect.value='number';
    else if(raw==='true'||raw==='false')typeSelect.value='boolean';
    else if(raw.startsWith('{')||raw.startsWith('['))typeSelect.value='object';
  });
  const descCell=document.createElement('td');
  const descInput=document.createElement('input');descInput.value=meta.description||'';descInput.placeholder='optional';descCell.append(descInput);
  if(meta.evidence_grade){const badge=document.createElement('span');badge.className=`grade grade-${meta.evidence_grade}`;badge.textContent=meta.evidence_grade.replaceAll('_',' ');badge.title=(meta.assumption_labels||[]).join(' ')||'Evidence grade recorded in the definition.';descCell.append(badge);}
  const remove=document.createElement('button');remove.className='remove-row';remove.textContent='Remove';remove.onclick=()=>{tr.remove();renderAgents(currentAgents);};
  const removeCell=document.createElement('td');removeCell.append(remove);
  [nameInput,typeSelect,valueInput].forEach(el=>{const td=document.createElement('td');td.append(el);tr.append(td);});
  tr.append(descCell);tr.append(removeCell);byId('variables').append(tr);
}
function worldVariableNames(){return [...byId('variables').rows].map(row=>row.querySelector('input')?.value.trim()).filter(Boolean);}
function availableActions(){try{return JSON.parse(actionBox.value||'[]');}catch{return [];}}
function control(labelText,element){const label=document.createElement('label');label.className='agent-field';label.append(document.createTextNode(labelText),element);return label;}
function renderAgents(agents){
  currentAgents=JSON.parse(JSON.stringify(agents||[]));const root=byId('agentsEditor');root.replaceChildren();
  const worldNames=worldVariableNames(), actions=availableActions();
  currentAgents.forEach((agent,index)=>{
    const card=document.createElement('article');card.className='agent-card';card.dataset.index=index;card.dataset.agentId=agent.id||'';
    const top=document.createElement('div');top.className='agent-card-head';const title=document.createElement('h3');title.textContent=agent.name||agent.id;top.append(title);
    const remove=document.createElement('button');remove.type='button';remove.className='remove-row';remove.textContent='Remove agent';remove.onclick=()=>{currentAgents.splice(index,1);renderAgents(currentAgents);syncAgentsFromForm();};top.append(remove);card.append(top);
    const fields=document.createElement('div');fields.className='agent-fields';
    const id=document.createElement('input');id.value=agent.id||'';id.readOnly=true;id.dataset.field='internalId';id.title='Internal reference used by actions and triggers';fields.append(control('Internal ID',id));
    const name=document.createElement('input');name.value=agent.name||'';name.dataset.field='name';fields.append(control('Display name',name));
    const type=document.createElement('select');const roleOptions=['generic','company','competitor','payer','physician','patient'];if(agent.type&&!roleOptions.includes(agent.type))roleOptions.push(agent.type);roleOptions.forEach(value=>{const option=new Option(value.replaceAll('_',' '),value);option.selected=value===(agent.type||'generic');type.add(option);});type.dataset.field='type';fields.append(control('Stakeholder type',type));
    const objective=document.createElement('textarea');objective.value=agent.objective||'';objective.rows=2;objective.dataset.field='objective';fields.append(control('What is this agent trying to do?',objective));card.append(fields);
    const triggers=safeTriggerList();
    const triggerSection=document.createElement('fieldset');triggerSection.className='choice-set';
    const triggerLegend=document.createElement('legend');triggerLegend.textContent='When this agent decides';triggerSection.append(triggerLegend);
    const triggerRow=document.createElement('div');triggerRow.className='trigger-row';
    const mode=agentTriggerMode(agent.id,triggers);
    const modeSelect=document.createElement('select');modeSelect.dataset.triggerMode='';
    const modes=[['start','Once at start'],['every','Every round'],['none','Never — this agent never decides']];
    if(mode==='custom')modes.unshift(['custom','Custom trigger (advanced JSON)']);
    modes.forEach(([val,text])=>{const option=new Option(text,val);option.selected=val===mode;modeSelect.add(option);});
    triggerRow.append(modeSelect);triggerSection.append(triggerRow);
    if(mode==='custom'){const custom=triggers.find(item=>item.id!==`auto-trigger-${agent.id}`&&item.affected_agents.includes(agent.id));
      triggerSection.append(note(`Managed in the advanced trigger JSON${custom?` as '${custom.id}'`:''}.`,'field-note'));}
    if(mode==='none')triggerSection.append(note('Without a trigger this agent is never asked to decide, and its actions are never used.','field-note'));
    card.append(triggerSection);
    const actionSection=document.createElement('fieldset');actionSection.className='choice-set';const actionLegend=document.createElement('legend');actionLegend.textContent='Choices this agent can make';actionSection.append(actionLegend);
    const ownActions=actions.filter(action=>action.agent_id===agent.id);
    if(!ownActions.length)actionSection.append(note('No actions yet — create the first one below.','field-note'));
    ownActions.forEach(action=>{const label=document.createElement('label');label.className='check-option';const input=document.createElement('input');input.type='checkbox';input.dataset.actionId=action.id;input.checked=(agent.available_actions||[]).includes(action.id);label.append(input,document.createTextNode(action.name||action.id));actionSection.append(label);});
    actionSection.append(actionBuilder(agent.id));card.append(actionSection);
    const observationSection=document.createElement('fieldset');observationSection.className='choice-set';const observationLegend=document.createElement('legend');observationLegend.textContent='What this agent can observe';observationSection.append(observationLegend);
    const allLabel=document.createElement('label');allLabel.className='check-option';const allInput=document.createElement('input');allInput.type='checkbox';allInput.dataset.observeAll='true';allInput.checked=agent.observable_state==='all';allLabel.append(allInput,document.createTextNode('All world variables'));observationSection.append(allLabel);
    const selected=Array.isArray(agent.observable_state)?agent.observable_state:[];
    worldNames.forEach(variable=>{const label=document.createElement('label');label.className='check-option';const input=document.createElement('input');input.type='checkbox';input.dataset.observation=variable;input.checked=selected.includes(variable);input.disabled=allInput.checked;label.append(input,document.createTextNode(variable.replaceAll('_',' ')));observationSection.append(label);});
    allInput.addEventListener('change',()=>{observationSection.querySelectorAll('[data-observation]').forEach(item=>item.disabled=allInput.checked);});
    card.append(observationSection);card.addEventListener('input',syncAgentsFromForm);card.addEventListener('change',syncAgentsFromForm);root.append(card);
  });
  attachHints(root);
}
function safeTriggerList(){try{const value=JSON.parse(triggerBox.value||'[]');return Array.isArray(value)?value:[];}catch{return [];}}
function agentTriggerMode(agentId,triggers){
  const auto=triggers.find(item=>item.id===`auto-trigger-${agentId}`);
  if(auto)return auto.event_types.includes('decision_round')?'every':'start';
  return triggers.some(item=>(item.affected_agents||[]).includes(agentId))?'custom':'none';
}
function slugify(text){return String(text).toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'')||'action';}
function parseValueInput(raw){
  if(/^-?\d+(\.\d+)?$/.test(raw))return Number(raw);
  if(raw==='true')return true;if(raw==='false')return false;
  return raw;
}
function actionBuilder(agentId){
  const box=document.createElement('div');box.className='action-builder';
  const name=document.createElement('input');name.placeholder='Action name (e.g. Lower price)';name.dataset.builderField='name';
  const worldNames=worldVariableNames();
  const variable=document.createElement('select');variable.dataset.builderField='variable';
  variable.append(new Option('Which variable changes…',''));
  worldNames.forEach(variableName=>variable.add(new Option(variableName,variableName)));
  const operation=document.createElement('select');operation.dataset.builderField='operation';
  [['set','sets it to'],['add','adds'],['subtract','subtracts'],['multiply','multiplies by'],['divide','divides by']].forEach(([val,text])=>operation.add(new Option(text,val)));
  const value=document.createElement('input');value.placeholder='value';value.dataset.builderField='value';
  const add=document.createElement('button');add.type='button';add.className='subtle';add.textContent='Add action';
  add.onclick=()=>addActionFromBuilder(agentId,box);
  const cell=el=>{const wrap=document.createElement('label');wrap.className='ab-cell';wrap.append(el);return wrap;};
  box.append(cell(name),cell(variable),cell(operation),cell(value),add);
  const react=document.createElement('label');react.className='builder-react check-option';
  const reactBox=document.createElement('input');reactBox.type='checkbox';reactBox.checked=true;reactBox.dataset.builderField='react';
  react.append(reactBox,document.createTextNode('Other agents can react to this choice (it emits an event)'));
  box.append(react);
  if(!worldNames.length)box.append(note('Add a world variable in step 2 first — actions change world variables.','field-note'));
  return box;
}
function addActionFromBuilder(agentId,box){
  const read=field=>box.querySelector(`[data-builder-field="${field}"]`);
  const name=read('name').value.trim(),variable=read('variable').value,operation=read('operation').value,rawValue=read('value').value.trim();
  if(!name||!variable||rawValue===''){setStatus('An action needs a name, a variable, and a value.',true);return;}
  const actions=readJsonBox(actionBox);
  const base=slugify(`${agentId}_${name}`);let id=base,n=2;
  while(actions.some(action=>action.id===id))id=`${base}_${n++}`;
  const action={id,name,agent_id:agentId,description:`${name} (added in the guided builder)`,
    effects:[{variable,operation,value:parseValueInput(rawValue)}]};
  if(read('react').checked)action.generated_events=[{event_type:id,description:`${name} was chosen by ${agentId}`}];
  actions.push(action);actionBox.value=JSON.stringify(actions,null,2);
  const agent=currentAgents.find(item=>item.id===agentId);
  if(agent)agent.available_actions=[...new Set([...(agent.available_actions||[]),id])];
  renderAgents(currentAgents);syncAgentsFromForm();
  setStatus(`Action '${name}' added to ${agentId}.`);
}
function syncTriggersFromForm(){
  let triggers=safeTriggerList();
  const modes={};
  document.querySelectorAll('#agentsEditor .agent-card').forEach(card=>{
    const agentId=card.dataset.agentId;if(!agentId)return;
    modes[agentId]=card.querySelector('[data-trigger-mode]')?.value||'none';});
  triggers=triggers.filter(item=>!String(item.id||'').startsWith('auto-trigger-'));
  Object.entries(modes).forEach(([agentId,mode])=>{
    if(mode==='start')triggers.push({id:`auto-trigger-${agentId}`,event_types:['simulation_start'],affected_agents:[agentId],priority:50});
    if(mode==='every')triggers.push({id:`auto-trigger-${agentId}`,event_types:['simulation_start','decision_round'],affected_agents:[agentId],priority:50});
  });
  triggerBox.value=JSON.stringify(triggers,null,2);
  syncRoundEvents(Object.values(modes).includes('every'));
  renderDefinitionSummaries();
}
function syncRoundEvents(needsRounds){
  let events=[];try{events=JSON.parse(byId('scheduledEvents').value||'[]');}catch{events=[];}
  events=events.filter(item=>!String(item.id||'').startsWith('auto-round-'));
  if(needsRounds){const horizon=Math.max(1,Math.floor(Number(byId('horizon').value)||4));
    for(let t=1;t<=horizon;t++)events.push({id:`auto-round-${t}`,time:t,event_type:'decision_round',
      description:'Guided builder round decision point',priority:40});}
  byId('scheduledEvents').value=JSON.stringify(events,null,2);
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
  syncTriggersFromForm();
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
  byId('llmMaxCalls').value=d.settings.llm_max_calls??'';byId('llmMaxTokens').value=d.settings.llm_max_total_tokens??'';
  byId('forecast').value=d.forecast_model_id||'state_metrics';byId('policy').value=d.scenario_generation.policy;
  syncForecastModelNote();
  byId('limit').value=d.scenario_generation.max_scenarios??9;byId('safety').value=d.scenario_generation.safety_limit??1000;
  byId('variables').replaceChildren();const vars=d.initial_world_state.variables||{};const metadata=d.world_variable_metadata||{};
  Object.entries(vars).forEach(([k,v])=>addVariableRow(k,v,metadata[k]||{}));
  agentBox.value=JSON.stringify(d.agents||[],null,2);actionBox.value=JSON.stringify(d.action_definitions||[],null,2);
  triggerBox.value=JSON.stringify(d.trigger_definitions||[],null,2);
  renderAgents(d.agents||[]);
  driverBox.value=JSON.stringify(d.external_drivers||[],null,2);renderDrivers(d.external_drivers||[]);
  byId('transitions').value=JSON.stringify(d.transition_rules||[],null,2);
  syncLlmFields();
  syncScenarioFields();
  renderDefinitionSummaries();
  applyHistorySelection(d.product_history_id||'');
  applyReferenceSelection(d);
  byId('initialEvents').value=JSON.stringify(d.settings.initial_events||[],null,2);byId('scheduledEvents').value=JSON.stringify(d.settings.scheduled_events||[],null,2);
  byId('errors').textContent='';clearResults();showWorkspace();syncDiscardButton();setStatus(isSaved?'Loaded saved simulation':'Template loaded');
}
function blankDefinition(){return {metadata:{id:'new-simulation',name:'New Simulation',description:'',domain:'general'},initial_world_state:{variables:{}},world_variable_metadata:{},evidence:[],agents:[],action_definitions:[],trigger_definitions:[],transition_rules:[],external_drivers:[],settings:{time_horizon:4,step_duration:1,step_unit:'round',decision_policy:'rule_based',initial_events:[{id:'start',time:0,event_type:'simulation_start',description:'Simulation begins'}],scheduled_events:[]},forecast_model_id:'state_metrics',product_history_id:null,scenario_generation:{policy:'diversity',max_scenarios:9,diversity_by_agents:[],safety_limit:1000}};}
function definitionFromForm(){
  const variables={}, variableMetadata={};
  [...byId('variables').rows].forEach(row=>{const [name,type,value,description]=[...row.querySelectorAll('input,select')];if(!name.value.trim())return;const key=name.value.trim();variables[key]=typedValue(value.value,type.value);
    const m={...(row._meta||{}),type:type.value};
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
    initial_events:parseBox('initialEvents',[]),scheduled_events:parseBox('scheduledEvents',[]),decision_policy:byId('decisionPolicy').value,
    llm_max_calls:optionalInt('llmMaxCalls'),llm_max_total_tokens:optionalInt('llmMaxTokens')};
  base.forecast_model_id=byId('forecast').value||null;
  base.product_history_id=byId('historySelect').value||null;
  base.reference_history_id=byId('refHistorySelect').value||null;
  const referencePeak=byId('refPeak').value.trim();
  if(referencePeak&&!Number.isFinite(Number(referencePeak)))throw new Error('Reference peak: enter a number, or leave it empty.');
  base.reference_peak=referencePeak===''?null:Number(referencePeak);
  base.reference_profile=byId('refProfile').value.trim().slice(0,4000);
  base.reference_rationale=referenceRationale.slice(0,600);
  const previousDiversity=base.scenario_generation?.diversity_by_agents||[];
  base.scenario_generation={...(base.scenario_generation||{}),policy:byId('policy').value,max_scenarios:Number(byId('limit').value),
    diversity_by_agents:Array.isArray(previousDiversity)&&previousDiversity.length?previousDiversity:agents.map(agent=>agent.id),
    safety_limit:Number(byId('safety').value)};
  return base;
}
async function request(url,options={}){const response=await fetch(url,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});let data;try{data=await response.json();}catch{data={};}if(!response.ok){const detail=data.detail;throw new Error(typeof detail==='string'?detail:detail?.errors?.join('\n')||JSON.stringify(detail)||response.statusText);}return data;}
async function save(){const definition=definitionFromForm();if(saved&&currentId===definition.metadata.id){await request(`/simulations/${encodeURIComponent(currentId)}`,{method:'PUT',body:JSON.stringify(definition)});}else{await request('/simulations',{method:'POST',body:JSON.stringify(definition)});saved=true;currentId=definition.metadata.id;}loadDefinition(definition,true);await refreshSaved();setStatus('Saved to local JSON');return definition;}
async function refreshSaved(){const items=await request('/simulations');const select=byId('savedSelect');const keep=select.value;select.replaceChildren(new Option('Choose saved simulation…',''));items.forEach(item=>select.add(new Option(item.name,item.simulation_id)));if(items.some(item=>item.simulation_id===keep))select.value=keep;/* The landing cards list the same files, so they refresh with the dropdown. */
  renderSavedCards(items);return items;}
async function refreshTemplates(){const items=await request('/simulations/templates');const select=byId('templateSelect');select.replaceChildren(new Option('Choose an example…',''));items.forEach(item=>{const option=new Option(item.name,item.id);option.title=item.description||'';select.add(option);});return items;}

/* ---------------- forecast catalog and stored product histories ---------------- */
/* Both lists come from the backend so a dropdown can never offer a model that is not
   registered, or a history that is not stored. */
async function refreshForecastModels(){
  const models=await request('/forecast/models');forecastModels=models;
  const select=byId('forecast');const keep=select.value;
  select.replaceChildren();
  const groups=[];
  models.forEach(model=>{
    let group=groups.find(entry=>entry.label===model.group);
    if(!group){group={label:model.group,options:[]};groups.push(group);}
    const option=new Option(model.label,model.model_id);
    option.title=[model.description,REQUIREMENT_HELP[model.requires]||''].filter(Boolean).join(' — ');
    group.options.push(option);});
  groups.forEach(group=>{
    const section=document.createElement('optgroup');section.label=group.label;
    group.options.forEach(option=>section.append(option));select.append(section);});
  select.value=keep||'state_metrics';
  syncForecastModelNote();
  return models;
}
function selectedForecastModel(){return forecastModels.find(model=>model.model_id===byId('forecast').value)||null;}
function syncForecastModelNote(){
  const model=selectedForecastModel();
  document.querySelectorAll('.history-only').forEach(el=>el.hidden=!model||model.requires!=='product_history');
  syncReferenceFields();
  byId('forecastNote').textContent=model
    ?`${model.label}: ${model.description} ${REQUIREMENT_HELP[model.requires]||''}`.trim()
    :'The forecast model list could not be read from the backend, so no forecast can be selected.';
}
async function refreshHistories(){
  const items=await request('/histories');storedHistories=items;
  const select=byId('historySelect');const keep=select.value;
  select.replaceChildren(new Option('Choose stored history…',''));
  items.forEach(item=>{
    const option=new Option(`${item.name} · ${item.points} points`,item.history_id);
    const users=(item.referenced_by||[]).length;
    option.title=[`${item.first} → ${item.latest}`,item.variable?`compares with ${item.variable}`:'kept under its own name',
      item.evidence_grade.replaceAll('_',' '),users?`used by ${users} saved simulation${users===1?'':'s'}`:'not used by any saved simulation']
      .filter(Boolean).join(' · ');
    select.append(option);});
  await applyHistorySelection(keep);
  refreshReferencePicker();
  /* The Analogue-Based Forecasting panel reads the same stored list, so a save or delete
     anywhere refreshes both pickers instead of leaving one offering a gone series. */
  if(typeof syncStandaloneHistories==='function')syncStandaloneHistories();
  return items;
}
async function applyHistorySelection(id){
  const select=byId('historySelect');
  /* A definition can point at a series that was deleted since. Showing the broken
     reference is better than silently clearing it and letting the run drop the input. */
  if(id&&!storedHistories.some(item=>item.history_id===id))select.append(new Option(`${id} (not stored)`,id));
  select.value=id||'';
  await syncHistoryPicker();
}
function storedHistory(id){return storedHistories.find(item=>item.history_id===id)||null;}
async function syncHistoryPicker(){
  const select=byId('historyVariable');const id=byId('historySelect').value;const item=storedHistory(id);
  const names=worldVariableNames();
  select.replaceChildren(new Option('Keep the history under its own name',''));
  names.forEach(name=>select.append(new Option(name,name)));
  if(item&&names.includes(item.variable))select.value=item.variable;
  const note=byId('historyNote');
  note.replaceChildren();
  if(!id){note.append(document.createTextNode('Nothing is stored yet. Import a CSV or Excel file in the forecaster on the home page, save the column as a product history, then pick it here.'));return;}
  if(!item){note.append(document.createTextNode(`'${id}' is not in histories/, so this run cannot use the historical forecast. Pick a stored series, or save the numbers again from the home page.`));return;}
  const users=(item.referenced_by||[]).length;
  note.append(document.createTextNode(
    `${item.name}: ${item.points} recorded periods, ${fmt(item.first)} → ${fmt(item.latest)}, graded ${item.evidence_grade.replaceAll('_',' ')}`
    +` from ${item.source||'an unstated source'}. `
    +`${item.variable?historyVariableMessage(item.variable,names):'Compared with nothing: the projection keeps the series name.'} `
    +(users?`Used by ${users} saved simulation${users===1?'':'s'}.`:'No saved simulation uses it yet.')));
  const remove=document.createElement('button');remove.type='button';remove.className='subtle';remove.textContent='Delete stored history';
  remove.onclick=deleteHistory;note.append(document.createTextNode(' '),remove);
}
function historyVariableMessage(variable,names){
  return names.includes(variable)?`Compared with world variable “${variable}”.`
    /* The comparison only happens if the run actually tracks that variable, so saying
       "compared with X" while X is absent would promise a number the run cannot report. */
    :`Marked as the history of “${variable}”, which is not a variable in this world — add it in step 2 or point the comparison below at one that exists.`;
}
async function deleteHistory(){
  const id=byId('historySelect').value;if(!id)return;
  const item=storedHistory(id);
  if(!confirm(`Delete histories/${id}.json${item?` ('${item.name}')`:''}? A deleted series is not recoverable.`))return;
  try{
    await request(`/histories/${encodeURIComponent(id)}`,{method:'DELETE'});
    byId('errors').textContent='';
    /* Drop the choice first: rebuilding the list with the deleted id still selected would
       immediately show it as a dangling reference to a series we just removed. */
    byId('historySelect').value='';
    await refreshHistories();
    setStatus(`Deleted product history '${id}'`);
  }catch(e){byId('errors').textContent=e.message;setStatus('Delete failed',true);}
}
async function compareHistoryWithVariable(){
  const id=byId('historySelect').value;if(!id)return;
  try{
    const stored=await request(`/histories/${encodeURIComponent(id)}`);
    await request(`/histories/${encodeURIComponent(id)}`,{method:'PUT',
      body:JSON.stringify({...stored,variable:byId('historyVariable').value})});
    await refreshHistories();
    setStatus(`Product history '${id}' now compared with ${byId('historyVariable').value||'nothing'}`);
  }catch(e){byId('errors').textContent=e.message;setStatus('Could not update the stored history',true);}
}
/* ---------------- reference-based forecasting ---------------- */
/* The reference series is another product's recorded ramp. Only its shape is borrowed:
   the peak entered here replaces the reference's own maximum, and every other period is
   multiplied by the same factor. The suggestion list changes nothing until a row is picked. */
function selectedReference(){return storedHistory(byId('refHistorySelect').value);}
function refreshReferencePicker(id){
  const select=byId('refHistorySelect');const keep=id===undefined?select.value:id;
  select.replaceChildren(new Option('Choose reference product…',''));
  storedHistories.forEach(item=>{
    const option=new Option(`${item.name} · peak ${fmt(item.peak)}`,item.history_id);
    option.title=[`recorded ${item.first} → ${item.latest} over ${item.points} periods`,
      `its own peak of ${fmt(item.peak)} is the value your peak replaces`,
      item.variable?`compares with ${item.variable}`:'compares with nothing',
      String(item.evidence_grade||'unspecified').replaceAll('_',' ')].join(' · ');
    select.append(option);});
  /* A definition can point at a series that was deleted since; showing the broken
     reference beats clearing it and letting the run silently lose the input. */
  if(keep&&!storedHistories.some(item=>item.history_id===keep))select.append(new Option(`${keep} (not stored)`,keep));
  select.value=keep||'';
  syncReferenceNote();
}
function syncReferenceNote(){
  const note=byId('refNote');note.replaceChildren();
  const item=selectedReference();
  const raw=byId('refPeak').value.trim();
  const peak=raw===''?null:Number(raw);
  if(!item){note.append(document.createTextNode(
    'Nothing selected yet. Import a CSV or Excel file in the forecaster on the home page, save a different product as a history, then pick it here — or describe this product above and ask the model to rank what is stored.'));return;}
  if(peak===null||!Number.isFinite(peak)||peak<=0){
    note.append(document.createTextNode(`'${item.name}' is chosen, but the peak field needs a positive number before this forecast can run.`));return;}
  const factor=peak/item.peak;
  const same=byId('historySelect').value===item.history_id;
  const compare=!item.variable?'No comparison variable is recorded on this series.'
    /* The gap metric only exists if the run actually tracks that variable, so promising a
       comparison against a name this world does not have would report a number never made. */
    :historyVariableMessage(item.variable,worldVariableNames());
  note.append(document.createTextNode(
    `${item.name}: its recorded peak of ${fmt(item.peak)} becomes ${fmt(peak)}, so every recorded period is multiplied by ${fmt(factor)}. `
    +(Math.abs(factor-1)<1e-9?'A 1.0× match, so the analogue is plotted exactly as it was recorded.'
      :'The shape is borrowed from that series; this peak is your assumption, not a measurement.')
    +(same?' This is the same series as the stored product history above, which validation rejects — pick a different product.':` ${compare}`)
    +` ${item.points} periods, graded ${String(item.evidence_grade||'unspecified').replaceAll('_',' ')} from ${item.source||'an unstated source'}.`));
}
async function requestReferenceSuggestion(){
  const profile=byId('refProfile').value.trim();
  const box=byId('refSuggestBox');
  if(profile.length<20){box.replaceChildren(defNote('Write at least 20 characters of product profile first — the model needs something to match against.'));return;}
  if(!storedHistories.length){box.replaceChildren(defNote('No product history is stored yet, so there is nothing to rank. Import and save a series in the forecaster on the home page first.'));return;}
  box.replaceChildren(defNote('Asking the model to rank the stored series…'));
  try{
    const payload=await request('/simulations/suggest-reference',{method:'POST',body:JSON.stringify({profile})});
    renderReferenceCandidates(payload,profile);
    setStatus(`${payload.candidates.length} reference product${payload.candidates.length===1?'':'s'} suggested by ${payload.provider_call.model||'the model'}`);
  }catch(e){
    box.replaceChildren(defNote(e.message));
    setStatus('The reference suggestion failed; nothing was changed',true);
  }
}
function renderReferenceCandidates(payload,profile){
  const box=byId('refSuggestBox');box.replaceChildren();
  if(!payload.candidates.length){
    box.append(defNote('The model returned no usable reference from the stored series'
      +(payload.rejected.length?' — every id it named was absent from histories/.':'.')));
    (payload.rejected||[]).forEach(item=>box.append(defNote(`It suggested “${item.history_id}”: ${item.reason}.`)));
    return;}
  const list=document.createElement('div');list.className='def-list';
  payload.candidates.forEach((candidate,index)=>{
    const row=document.createElement('div');row.className='def-row';
    const label=document.createElement('span');label.className='def-key';
    label.textContent=`${index+1}. ${candidate.name}`;
    const chips=document.createElement('div');chips.className='def-chips';
    [candidate.reason||'no reason given',
     ...(candidate.cited_profile_text||[]).map(quote=>`profile: “${quote}”`),
     ...(candidate.unmatched_quotes||[]).map(quote=>`not from your profile: “${quote}”`)]
      .forEach(text=>{const chip=document.createElement('span');chip.className='def-chip';chip.textContent=text;chips.append(chip);});
    const use=document.createElement('button');use.type='button';use.className='subtle';use.textContent='Use as reference';
    use.onclick=()=>applyReferenceCandidate(candidate,profile);
    row.append(label,chips,use);list.append(row);});
  box.append(list);
  const usage=payload.provider_call||{};
  box.append(defNote(`Ranked from ${payload.histories_offered} stored series by ${usage.model||'a model'} in ${Math.round(usage.latency_ms||0)} ms `
    +`(${usage.total_tokens||0} tokens, one call). The ranking is a suggestion: the reference, the peak and the fit stay yours.`));
  if((payload.rejected||[]).length)box.append(defNote(payload.rejected.map(item=>`Ignored “${item.history_id}”: ${item.reason}.`).join(' ')));
}
function applyReferenceCandidate(candidate,profile){
  byId('refHistorySelect').value=candidate.history_id;
  /* Prefill the peak only when nothing is typed yet: copying the reference's own maximum
     is a 1.0× match, which is the honest place to start editing from. */
  const item=selectedReference();
  if(item&&!byId('refPeak').value.trim())byId('refPeak').value=item.peak;
  const cited=(candidate.cited_profile_text||[]);
  referenceRationale=`${candidate.name}: ${candidate.reason||'ranked by the model'}`
    +(cited.length?` — cited “${cited.join(' | ')}”`:' — no profile text matched verbatim')
    +`, applied from a profile match by you.`;
  syncReferenceNote();
  setStatus(`Reference set to ${candidate.name}; check the peak value, then Save`);
}
function applyReferenceSelection(definition){
  byId('refProfile').value=definition.reference_profile||'';
  byId('refPeak').value=definition.reference_peak??'';
  referenceRationale=definition.reference_rationale||'';
  refreshReferencePicker(definition.reference_history_id||'');
}
function syncReferenceFields(){
  const model=selectedForecastModel();
  const shown=Boolean(model&&model.requires==='reference_product');
  document.querySelectorAll('.reference-only').forEach(el=>el.hidden=!shown);
  if(!shown)byId('refSuggestBox').replaceChildren();
  else syncReferenceNote();
}
function clearResults(){
  const placeholder=(id,text)=>{const box=byId(id);box.textContent=text;box.classList.add('muted');};
  placeholder('summary','Run a simulation to view results.');placeholder('charts','Run a simulation to compare outcomes visually.');
  placeholder('scenarioDetail','Select a terminal scenario in the flowchart, tree, or comparison table.');placeholder('tree','The tree will appear here after a run.');
  byId('comparison').querySelector('thead').replaceChildren();byId('comparison').querySelector('tbody').replaceChildren();
  clearDashboard();resultScenarios=[];nodeIndex={};showTab('overview');
}
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
    row.append(first);keys.forEach(k=>{const td=document.createElement('td');const value=s.forecast?.metrics?.[k];
      td.textContent=typeof value==='number'?(Math.abs(value)>=1000?Math.round(value).toLocaleString():Number(value.toFixed(4))):value??'—';row.append(td)});body.append(row);});
}
const METRIC_TITLES={cumulative_sales:'Cumulative modeled sales',peak_sales:'Peak modeled sales',patients_treated:'Patients treated (modeled)',market_share:'Market share (modeled)'};
const METRIC_SUFFIXES=[['_trend_per_period','change per period'],['_projected','projected past the horizon'],
  ['_driver_delta','extra effect the drivers add past the horizon'],
  ['_history_gap','difference between the recorded trend and this run'],
  ['_reference_gap','difference between the scaled reference analogue and this run'],
  ['_simulated','value this run actually ended at']];
/* Counts about the forecast itself, not about any variable, so they are not labelled as
   if they were world values. */
const SUMMARY_METRICS=new Set(['drivers_projected','driver_pathways_not_projected',
  'history_points','history_start','history_latest','history_rmse',
  'reference_product','reference_points','reference_recorded_peak','reference_peak_target',
  'reference_scale','reference_latest_scaled','reference_rmse']);
/* Chart slots are capped, so the numbers that describe a series take them before the
   counts that only describe how the forecast was computed. */
function metricChartRank(key){return METRIC_TITLES[key]?0:SUMMARY_METRICS.has(key)?2:1;}
function metricBase(key){const hit=METRIC_SUFFIXES.find(([token])=>key.endsWith(token));return hit?key.slice(0,-hit[0].length):key;}
function formatChartValue(metric,value){
  const base=metricBase(metric);
  if(base==='market_share')return `${(value*100).toFixed(2)}%`;
  if(base==='patients_treated')return Math.round(value).toLocaleString();
  if(METRIC_TITLES[metric])return Number(value).toLocaleString(undefined,{maximumFractionDigits:0})+' scenario currency';
  return Number(value).toLocaleString(undefined,{maximumFractionDigits:4});
}
function metricHeading(key,historyName,referenceName){
  const heading=document.createElement('h3');
  if(METRIC_TITLES[key]){heading.textContent=METRIC_TITLES[key];return heading;}
  const suffix=METRIC_SUFFIXES.find(([token])=>key.endsWith(token));
  const base=suffix?key.slice(0,-suffix[0].length):key;
  heading.textContent=metricKind(key,base,historyName,referenceName);
  const code=document.createElement('code');code.textContent=base;
  heading.append(code);
  if(suffix)heading.append(document.createTextNode(` — ${suffix[1]}`));
  return heading;
}
function metricKind(key,base,historyName,referenceName){
  if(SUMMARY_METRICS.has(key))return key.startsWith('reference_')?'Reference analogue: ':'Forecast summary: ';
  if(base.endsWith('_level'))return 'External driver: ';
  if(historyName&&base===historyName)return 'Stored history: ';
  if(referenceName&&base===referenceName)return 'Reference product: ';
  return 'World variable: ';
}
function drawCharts(scenarios,summary){
  const root=byId('charts');root.replaceChildren();root.classList.remove('muted');
  const history=summary?.product_history;
  const historyName=history&&!history.missing?history.name:'';
  const reference=summary?.reference_history;
  const referenceName=reference&&!reference.missing?reference.name:'';
  const metrics=new Set(scenarios.flatMap(s=>Object.keys(s.forecast?.metrics||{})));
  const keys=[...metrics].filter(key=>key!=='time'&&scenarios.some(s=>typeof s.forecast?.metrics?.[key]==='number'))
    .sort((a,b)=>metricChartRank(a)-metricChartRank(b)||a.localeCompare(b));
  if(!keys.length){
    root.textContent=metrics.size
      ?'The selected forecast returned no numeric metrics, so there is nothing to chart. The scenario comparison table still lists every recorded value.'
      :'No forecast was attached to this run, so there is nothing to chart. Pick a forecast model in step 1, or give an agent objective that cites forecast metrics.';
    return;
  }
  keys.slice(0,6).forEach(key=>{
    const section=document.createElement('section');section.className='metric-chart';section.append(metricHeading(key,historyName,referenceName));
    const values=scenarios.map(s=>Number(s.forecast?.metrics?.[key]||0));const max=Math.max(...values,0);
    scenarios.forEach((scenario,index)=>{const row=document.createElement('div');row.className='bar-row';const label=document.createElement('span');label.className='bar-label';label.textContent=scenario.name;label.title=scenario.name;const track=document.createElement('div');track.className='bar-track';const bar=document.createElement('div');bar.className='bar-fill';bar.style.width=max>0?`${Math.max(0,values[index]/max*100)}%`:'0%';track.append(bar);const value=document.createElement('strong');value.textContent=formatChartValue(key,values[index]);row.append(label,track,value);section.append(row);});
    if(max===0)section.append(note('Every retained scenario is zero for this metric. Check that the definition actually produces values for it; the engine reports what it recorded, not what it expected.','zero-note'));
    root.append(section);
  });
  if(keys.length>6)root.append(note(`Showing the first 6 of ${keys.length} numeric forecast metrics. All of them are listed in the scenario comparison table.`));
  const note2=document.createElement('p');note2.className='assumption-note';note2.textContent='Charts visualize the configured model only. Example values are synthetic and uncalibrated.';root.append(note2);
}
const GAP_LABELS={variable_value:'World value',agent_objective:'Agent objective',agent_actions:'Action',agent_trigger:'Decision timing'};
function renderGapReport(gaps){
  const box=byId('gapReport');box.hidden=false;box.replaceChildren();
  const head=document.createElement('h3');head.textContent=gaps.filled.length?`Model-supplied assumptions (${gaps.filled.length})`:'Model-supplied assumptions';box.append(head);
  const intro=document.createElement('p');intro.className='assumption-note';
  intro.textContent='These values were written by the model, not measured or entered by you. Each one is labeled in the builder and stays editable.';box.append(intro);
  if(gaps.filled.length){const list=document.createElement('ul');list.className='gap-list';
    gaps.filled.forEach(item=>{const li=document.createElement('li');const label=document.createElement('b');
      label.textContent=`${GAP_LABELS[item.kind]||item.kind} · ${item.key}`;li.append(label);
      li.append(document.createTextNode(` ${typeof item.value==='string'?item.value:JSON.stringify(item.value)}`));
      if(item.rationale)li.append(document.createTextNode(` — ${item.rationale}`));list.append(li);});
    box.append(list);}
  else{const none=document.createElement('p');none.className='muted';
    none.textContent=gaps.gaps.length?'The model returned nothing that passed validation, so the definition is unchanged.':'Nothing to fill — every value needed for a run is already entered.';box.append(none);}
  if(gaps.rejected&&gaps.rejected.length){const details=document.createElement('details');details.className='advanced';
    const summary=document.createElement('summary');summary.textContent=`${gaps.rejected.length} model suggestion(s) were not applied`;details.append(summary);
    const list=document.createElement('ul');list.className='gap-list';
    gaps.rejected.forEach(item=>{const li=document.createElement('li');li.textContent=`${item.key}: ${item.reason}`;list.append(li);});
    details.append(list);box.append(details);}
  if(gaps.provider_call){const usage=document.createElement('p');usage.className='field-note';
    usage.textContent=`One provider call: ${gaps.provider_call.model}, ${gaps.provider_call.total_tokens} tokens.`;box.append(usage);}
}
async function fillGapsWithAssumptions(){
  setProgress('Asking the model to fill the values you left blank…',6);
  const gaps=await request('/simulations/complete-gaps',{method:'POST',body:JSON.stringify(definitionFromForm())});
  byId('llmFillGaps').checked=false;
  renderGapReport(gaps);
  if(!gaps.filled.length)return;
  const wasSaved=saved,previousId=currentId;
  loadDefinition(gaps.definition,true);
  saved=wasSaved;currentId=previousId;
  setStatus(`Model filled ${gaps.filled.length} blank value${gaps.filled.length===1?'':'s'} — review them before the results below.`);
}
async function runSimulation(){
  byId('gapReport').hidden=true;
  if(byId('llmFillGaps').checked)await fillGapsWithAssumptions();
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
  const decisions=results.scenarios.flatMap(s=>s.decision_trace||[]).filter(t=>t.event_type==='decision');
  const valid=decisions.filter(t=>t.validation_status==='valid').length;
  let runWarning='';
  if(!decisions.length)runWarning='No decisions were made: no trigger fired for any agent. Set when each agent decides in step 3.';
  else if(!valid)runWarning='Every decision this run was rejected because the triggered agents had no feasible actions. Add actions to each agent card in step 3 so the decision policy has choices to select from.';
  if(runWarning)byId('errors').textContent=runWarning;
  showTab('overview');
  setProgress(`Run complete: ${runInfo.scenario_count} scenario${runInfo.scenario_count===1?'':'s'} in ${runInfo.duration_seconds.toFixed(3)}s`,100);
  setStatus(runWarning||`Run complete: ${runInfo.scenario_count} scenarios`,Boolean(runWarning));
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
byId('discardBtn').onclick=async()=>{
  const id=currentId;if(!(saved&&id))return;
  const name=byId('name').value.trim()||id;
  if(!confirm(`Discard '${name}'? This deletes simulations/${id}.json and clears the editor. A deleted file is not recoverable.`))return;
  try{
    await request(`/simulations/${encodeURIComponent(id)}`,{method:'DELETE'});
    startBlank();await refreshSaved();
    setStatus(`Discarded '${name}' — the saved file was deleted`);
  }catch(e){byId('errors').textContent=e.message;setStatus('Discard failed',true);syncDiscardButton();}
};
byId('savedSelect').onchange=async()=>{const id=byId('savedSelect').value;if(!id)return;try{const d=await request(`/simulations/${encodeURIComponent(id)}`);loadDefinition(d.definition,true);}catch(e){setStatus(e.message,true);}};

/* ---------------- result panels and read-only definition maps ---------------- */
function showTab(name){
  document.querySelectorAll('.results .tab').forEach(tab=>{const on=tab.dataset.tab===name;tab.classList.toggle('is-active',on);tab.setAttribute('aria-selected',String(on));});
  document.querySelectorAll('.results .tabpanel').forEach(panel=>{panel.hidden=panel.id!==`panel-${name}`;});
}
function syncLlmFields(){
  const on=byId('decisionPolicy').value==='llm';
  document.querySelectorAll('.llm-only').forEach(el=>el.hidden=!on);
}
function syncScenarioFields(){
  const policy=byId('policy').value,exhaustive=policy==='exhaustive';
  document.querySelectorAll('.policy-counted').forEach(el=>el.hidden=exhaustive);
  document.querySelectorAll('.policy-exhaustive').forEach(el=>el.hidden=!exhaustive);
  byId('policyNote').textContent=exhaustive
    ?'Exhaustive keeps every branch it generates, so only the total node safety limit is read. The scenario limit has no effect on this policy.'
    :`The scenario limit caps this run${policy==='diversity'?' by keeping the most distinct branches per agent':' by keeping the best-scoring branches'}. The total node safety limit is read only by the Exhaustive policy.`;
}
byId('decisionPolicy').addEventListener('change',syncLlmFields);
byId('policy').addEventListener('change',syncScenarioFields);
byId('horizon').addEventListener('change',()=>syncTriggersFromForm());
document.querySelectorAll('.results .tab').forEach(tab=>tab.onclick=()=>showTab(tab.dataset.tab));

function readJsonBox(box){try{const value=JSON.parse(box.value||'[]');return Array.isArray(value)?value:[];}catch{return [];}}
function defNote(text){const p=document.createElement('p');p.className='def-empty';p.textContent=text;return p;}
function defRow(key,items,tally){
  const row=document.createElement('div');row.className='def-row';
  const label=document.createElement('span');label.className='def-key';label.textContent=key;
  const chips=document.createElement('div');chips.className='def-chips';
  items.forEach(({text,title})=>{const chip=document.createElement('span');chip.className='def-chip';if(title)chip.title=title;chip.textContent=text;chips.append(chip);});
  row.append(label,chips);
  if(tally){const count=document.createElement('span');count.className='def-tally';count.textContent=tally;row.append(count);}
  return row;
}
function renderDefinitionSummaries(){
  const actions=readJsonBox(actionBox), triggers=readJsonBox(triggerBox);
  const actionRoot=byId('actionSummary'), triggerRoot=byId('triggerSummary');
  actionRoot.replaceChildren();triggerRoot.replaceChildren();

  const byAgent=new Map();
  actions.forEach(action=>{const key=action.agent_id||'unassigned';if(!byAgent.has(key))byAgent.set(key,[]);byAgent.get(key).push(action);});
  if(!actions.length)actionRoot.append(defNote('No actions defined yet. Use “Add action” on an agent card in step 3, or the advanced JSON below.'));
  byAgent.forEach((items,agent)=>{
    const chips=items.map(action=>{
      const variables=(action.effects||[]).map(effect=>effect.variable);
      return {text:action.name||action.id,
              title:action.description||`Transition: ${variables.join(', ')||'no state effects'}`};
    });
    actionRoot.append(defRow(agent,chips,`${items.length} action${items.length===1?'':'s'}`));
  });

  if(!triggers.length)triggerRoot.append(defNote('No triggers defined yet, so no agent will ever be asked to decide. Set “When this agent decides” on each agent card in step 3.'));
  triggers.forEach(trigger=>{
    const items=(trigger.event_types||[]).map(event=>({text:`on ${event}`}));
    (trigger.affected_agents||[]).forEach(agent=>items.push({text:`${agent} decides`}));
    if(trigger.state_condition)items.push({text:'when state matches',title:JSON.stringify(trigger.state_condition)});
    if(trigger.cooldown)items.push({text:`cooldown ${trigger.cooldown}`});
    if(trigger.expires_after)items.push({text:`expires after ${trigger.expires_after}`});
    triggerRoot.append(defRow(trigger.id,items,trigger.priority?`priority ${trigger.priority}`:''));
  });
  /* The stored history is compared against a world variable, so this list follows the
     variable table rather than being built somewhere else. */
  syncHistoryPicker();
}
actionBox.addEventListener('change',renderDefinitionSummaries);
triggerBox.addEventListener('change',renderDefinitionSummaries);
byId('forecast').addEventListener('change',syncForecastModelNote);
byId('historySelect').addEventListener('change',syncHistoryPicker);
byId('historyVariable').addEventListener('change',compareHistoryWithVariable);
byId('refHistorySelect').addEventListener('change',syncReferenceNote);
byId('refPeak').addEventListener('input',syncReferenceNote);
byId('refSuggestBtn').onclick=requestReferenceSuggestion;
renderDefinitionSummaries();