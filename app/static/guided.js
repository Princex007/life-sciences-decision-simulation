/* Landing view, guided external-driver editor, run progress, variant comparison. */

const GRADE_HELP = {
  empirical: 'Sourced from stated empirical input configured in the definition.',
  user_assumption: 'A value you set. It is not a measurement.',
  model_hypothesis: 'Produced by the model. It is a hypothesis, not an observation.',
  synthetic_illustrative: 'Synthetic placeholder for demonstration. Not calibrated to any real market.',
  unspecified: 'No evidence grade was recorded for this value.'
};
const DRIVER_CATEGORIES = ['technology','regulatory','market','economic','payer','clinical','competitive','unspecified'];

function showHome(){byId('viewHome').hidden=false;byId('viewWorkspace').hidden=true;}
function showWorkspace(){byId('viewHome').hidden=true;byId('viewWorkspace').hidden=false;}
function setProgress(text,pct){const box=byId('progress');box.hidden=false;byId('progressText').textContent=text;byId('progressBar').style.width=`${Math.max(0,Math.min(100,Number(pct)||0))}%`;}
function hideProgress(){byId('progress').hidden=true;}
function gradeBadge(grade){
  const span=document.createElement('span');span.className=`grade grade-${grade||'unspecified'}`;
  span.textContent=(grade||'unspecified').replaceAll('_',' ');span.title=GRADE_HELP[grade]||GRADE_HELP.unspecified;return span;
}
function note(text,className='field-note'){const p=document.createElement('p');p.className=className;p.textContent=text;return p;}
function chip(text){const li=document.createElement('li');li.className='chip';li.textContent=text;return li;}
function configuredAgents(){try{return JSON.parse(agentBox.value||'[]');}catch{return [];}}

/* ---------------- landing view ---------------- */
async function refreshHome(){
  try{
    const [templates,savedList]=await Promise.all([refreshTemplates(),refreshSaved()]);
    renderExampleCards(templates);renderSavedCards(savedList);
  }catch(error){
    byId('exampleCards').replaceChildren(note(`Could not load examples: ${error.message}`,'assumption-note'));
    byId('savedCards').replaceChildren(note(`Could not load saved simulations: ${error.message}`,'assumption-note'));
  }
}
function exampleCard(item){
  const summary=item.summary||{};const card=document.createElement('article');card.className='example-card';
  const title=document.createElement('h3');title.textContent=item.name;card.append(title);
  if(item.description){const p=document.createElement('p');p.className='example-desc';p.textContent=item.description;card.append(p);}
  const chips=document.createElement('ul');chips.className='chips';
  chips.append(chip(`${(summary.agents||[]).length} agents`),chip(`${summary.time_horizon} ${summary.step_unit||'step'}s`),
    chip(`forecast: ${(summary.forecast_model||'none').replaceAll('_',' ')}`),chip(`up to ${summary.max_scenarios??'—'} scenarios`));
  (summary.external_drivers||[]).forEach(driver=>chips.append(chip(`driver: ${driver.name}`)));
  (summary.evidence_grades||[]).forEach(grade=>chips.append(chip(grade.replaceAll('_',' '))));
  card.append(chips);
  if((summary.external_drivers||[]).length){
    const line=document.createElement('p');line.className='driver-line';
    line.textContent=summary.external_drivers.map(driver=>{
      const active=(driver.variants||[]).find(v=>v.variant_id===driver.active_variant);
      return `${driver.name} — variant “${active?.label||driver.active_variant}”`;}).join('; ');
    card.append(line);
  }
  card.append(note('Synthetic, illustrative values. Not a market forecast or clinical evidence.','assumption-note small'));
  const actions=document.createElement('div');actions.className='card-actions';
  const run=document.createElement('button');run.className='primary';run.textContent='Load and run';
  run.onclick=async()=>{try{await loadTemplate(item.id);await runSimulation();}catch(error){byId('errors').textContent=error.message;setStatus('Example run failed',true);}};
  const edit=document.createElement('button');edit.className='subtle';edit.textContent='Customize first';
  edit.onclick=async()=>{try{await loadTemplate(item.id);}catch(error){byId('errors').textContent=error.message;setStatus('Example load failed',true);}};
  actions.append(run,edit);card.append(actions);return card;
}
function renderExampleCards(templates){
  const grid=byId('exampleCards');grid.replaceChildren();
  if(!templates.length){grid.append(note('No bundled examples were found in examples/.'));return;}
  templates.forEach(item=>grid.append(exampleCard(item)));
}
function savedCard(item){
  const card=document.createElement('article');card.className='example-card';
  const title=document.createElement('h3');title.textContent=item.name;card.append(title);
  if(item.description){const p=document.createElement('p');p.className='example-desc';p.textContent=item.description;card.append(p);}
  const chips=document.createElement('ul');chips.className='chips';
  chips.append(chip(`${item.agent_count} agents`),chip(`${item.time_horizon} steps`),chip(item.simulation_id));
  if(item.external_driver_count)chips.append(chip(`${item.external_driver_count} drivers`));
  if(item.has_results)chips.append(chip('results in memory'));
  card.append(chips);
  const actions=document.createElement('div');actions.className='card-actions';
  const open=document.createElement('button');open.className='subtle';open.textContent='Open';
  open.onclick=async()=>{try{const data=await request(`/simulations/${encodeURIComponent(item.simulation_id)}`);loadDefinition(data.definition,true);}catch(error){setStatus(error.message,true);}};
  const run=document.createElement('button');run.className='primary';run.textContent='Open and run';
  run.onclick=async()=>{try{const data=await request(`/simulations/${encodeURIComponent(item.simulation_id)}`);loadDefinition(data.definition,true);await runSimulation();}catch(error){byId('errors').textContent=error.message;setStatus('Run failed',true);}};
  actions.append(open,run);card.append(actions);return card;
}
function renderSavedCards(items){
  const grid=byId('savedCards');grid.replaceChildren();
  if(!items.length){grid.append(note('Nothing saved yet. Load an example or start from scratch, then use Save Simulation.'));return;}
  items.forEach(item=>grid.append(savedCard(item)));
}
function startBlank(){
  const definition=blankDefinition();
  definition.metadata.id=`new-simulation-${String(Date.now()).slice(-6)}`;
  loadDefinition(definition,false);
  saved=false;currentId=null;
  setStatus('Blank simulation ready. Add world variables and agents, then validate before running.');
}
async function initHome(){
  byId('homeBtn').onclick=async()=>{await refreshHome();showHome();};
  byId('startScratchBtn').onclick=startBlank;
  await refreshHome();
  loadDefinition(blankDefinition(),false);
  showHome();
}

/* ---------------- guided external-driver editor ---------------- */
function renderDrivers(drivers){
  currentDrivers=JSON.parse(JSON.stringify(drivers||[]));
  const root=byId('driversEditor');root.replaceChildren();
  if(!currentDrivers.length){
    root.append(note('No external drivers are configured, so this run reflects agent decisions and scheduled events only. Load an example that includes drivers, or add one in the advanced JSON below.'));
    return;
  }
  const agents=configuredAgents();
  currentDrivers.forEach((driver,index)=>{
    const card=document.createElement('article');card.className='agent-card driver-card';card.dataset.index=index;
    const head=document.createElement('div');head.className='agent-card-head';
    const title=document.createElement('h3');title.textContent=driver.name||driver.driver_id;head.append(title);
    const headRight=document.createElement('div');headRight.className='head-right';
    headRight.append(gradeBadge(driver.evidence_grade));
    const active=document.createElement('label');active.className='check-option';
    const activeBox=document.createElement('input');activeBox.type='checkbox';activeBox.checked=driver.enabled!==false;activeBox.dataset.field='enabled';
    active.append(activeBox,document.createTextNode('Active in this run'));headRight.append(active);
    const remove=document.createElement('button');remove.type='button';remove.className='remove-row';remove.textContent='Remove driver';
    remove.onclick=()=>{currentDrivers.splice(index,1);renderDrivers(currentDrivers);syncDriversFromForm();};
    headRight.append(remove);head.append(headRight);card.append(head);

    const fields=document.createElement('div');fields.className='agent-fields';
    fields.append(driverControl('Display name',textInput(driver.name||'',driver,'name')));
    const category=document.createElement('select');
    DRIVER_CATEGORIES.concat((driver.category&&!DRIVER_CATEGORIES.includes(driver.category))?[driver.category]:[]).forEach(value=>{
      const option=new Option(value,value);option.selected=value===(driver.category||'unspecified');category.add(option);});
    category.dataset.field='category';fields.append(driverControl('Category',category));
    const variant=document.createElement('select');
    (driver.variants||[]).forEach(item=>{const option=new Option(item.label||item.variant_id,item.variant_id);option.selected=item.variant_id===(driver.active_variant||'');variant.add(option);});
    if(!(driver.variants||[]).length){const option=new Option('No variants configured','');option.selected=true;variant.add(option);}
    variant.dataset.field='active_variant';fields.append(driverControl('World variant',variant));
    const observableFrom=document.createElement('input');observableFrom.type='number';observableFrom.min='0';observableFrom.value=driver.observable_from??0;observableFrom.dataset.field='observable_from';
    fields.append(driverControl('Observable from time',observableFrom));
    const priority=document.createElement('input');priority.type='number';priority.value=driver.priority??50;priority.dataset.field='priority';
    fields.append(driverControl('Event priority',priority));
    const indicator=document.createElement('input');indicator.value=driver.indicator_variable||'';indicator.placeholder='optional world variable';indicator.dataset.field='indicator_variable';
    fields.append(driverControl('Indicator variable',indicator));
    const initialValue=document.createElement('input');initialValue.type='number';initialValue.step='any';initialValue.value=driver.initial_value??0;initialValue.dataset.field='initial_value';
    fields.append(driverControl('Initial indicator value',initialValue));
    const description=document.createElement('textarea');description.rows=2;description.value=driver.description||'';description.dataset.field='description';
    fields.append(driverControl('What does this driver represent?',description));
    card.append(fields);

    const observe=document.createElement('fieldset');observe.className='choice-set';
    const observeLegend=document.createElement('legend');observeLegend.textContent='Which agents can observe the indicator';observe.append(observeLegend);
    if(!driver.indicator_variable)observe.append(note('Set an indicator variable to let agents observe this driver.'));
    agents.forEach(agent=>{
      const label=document.createElement('label');label.className='check-option';
      const input=document.createElement('input');input.type='checkbox';input.dataset.observeAgent=agent.id;
      input.checked=(driver.observable_by||[]).includes(agent.id);input.disabled=!driver.indicator_variable;
      label.append(input,document.createTextNode(agent.name||agent.id));observe.append(label);});
    card.append(observe);

    card.append(variantStrip(driver,index));
    card.append(pathwayTable(driver));
    const labels=driverAssumptionLabels(driver);
    if(labels.length)card.append(assumptionLabelList(labels));
    card.addEventListener('input',syncDriversFromForm);card.addEventListener('change',syncDriversFromForm);
    root.append(card);
  });
}
function driverControl(labelText,element){const label=document.createElement('label');label.className='agent-field';label.append(document.createTextNode(labelText),element);return label;}
function textInput(value,driver,field){const input=document.createElement('input');input.value=value;input.dataset.field=field;return input;}
function driverAssumptionLabels(driver){
  const labels=[];
  if(driver.assumption_label)labels.push(driver.assumption_label);
  const variant=(driver.variants||[]).find(item=>item.variant_id===driver.active_variant);
  if(variant&&variant.assumption_label)labels.push(variant.assumption_label);
  return labels;
}
function assumptionLabelList(labels){
  const box=document.createElement('div');box.className='assumption-box';
  const heading=document.createElement('b');heading.textContent='Assumption labels carried into results';box.append(heading);
  const list=document.createElement('ul');
  labels.forEach(text=>{const li=document.createElement('li');li.textContent=text;list.append(li);});
  box.append(list);return box;
}
function variantStrip(driver,index){
  const section=document.createElement('div');section.className='variant-strip';
  const heading=document.createElement('b');heading.textContent='Configured variants';section.append(heading);
  const variants=driver.variants||[];
  if(!variants.length){section.append(note('This driver has a single fixed trajectory. Add variants in the advanced JSON to compare alternative worlds.'));return section;}
  variants.forEach(variant=>{
    const tile=document.createElement('div');tile.className='variant-tile';
    if(variant.variant_id===driver.active_variant)tile.classList.add('active');
    const name=document.createElement('strong');name.textContent=variant.label||variant.variant_id;tile.append(name);
    tile.append(gradeBadge(variant.evidence_grade||driver.evidence_grade));
    if(variant.description){const p=document.createElement('p');p.textContent=variant.description;tile.append(p);}
    if(variant.assumption_label){const small=document.createElement('small');small.className='muted';small.textContent=variant.assumption_label;tile.append(small);}
    const points=(variant.trajectory||[]).map(point=>`t${point.time}: ×${point.level}`).join('  ');
    if(points){const code=document.createElement('code');code.textContent=points;tile.append(code);}
    const use=document.createElement('button');use.type='button';use.className='subtle';use.textContent='Use this variant';
    use.disabled=variant.variant_id===driver.active_variant;
    use.onclick=()=>{const select=byId('driversEditor').querySelector(`.driver-card[data-index="${index}"] [data-field="active_variant"]`);if(select){select.value=variant.variant_id;syncDriversFromForm();renderDrivers(currentDrivers);}};
    tile.append(use);section.append(tile);
  });
  const compare=document.createElement('button');compare.type='button';compare.className='primary compare-variants';
  compare.textContent=`Compare all ${variants.length} variants`;compare.onclick=()=>compareVariants(index);
  section.append(compare);return section;
}
function pathwayTable(driver){
  const wrap=document.createElement('div');wrap.className='pathway-wrap';
  const heading=document.createElement('b');heading.textContent='Configured pathways';wrap.append(heading);
  const pathways=driver.pathways||[];
  if(!pathways.length){wrap.append(note('No pathways configured, so this driver only publishes an indicator.'));return wrap;}
  const table=document.createElement('table');
  const head=document.createElement('thead');const headRow=document.createElement('tr');
  ['Target variable','Operation','Configured value','Lag','Bounds','Grade',''].forEach(text=>{const th=document.createElement('th');th.textContent=text;headRow.append(th);});
  head.append(headRow);table.append(head);
  const body=document.createElement('tbody');
  pathways.forEach(pathway=>{
    const row=document.createElement('tr');
    const target=document.createElement('td');target.textContent=pathway.target_variable.replaceAll('_',' ');row.append(target);
    const operation=document.createElement('td');operation.textContent=pathway.operation;row.append(operation);
    const value=document.createElement('td');value.textContent=pathway.qualitative_only?'not quantified':String(pathway.value);row.append(value);
    const lag=document.createElement('td');lag.textContent=pathway.lag?`+${pathway.lag}`:'0';row.append(lag);
    const bounds=document.createElement('td');bounds.textContent=(pathway.minimum!=null||pathway.maximum!=null)?`${pathway.minimum??'−∞'} … ${pathway.maximum??'∞'}`:'—';row.append(bounds);
    const grade=document.createElement('td');grade.append(gradeBadge(pathway.evidence_grade));row.append(grade);
    const flags=document.createElement('td');
    if(pathway.qualitative_only){const badge=document.createElement('span');badge.className='grade grade-model_hypothesis';badge.textContent='qualitative only — never converted to a number';badge.title=pathway.uncertainty||'Recorded as a hypothesis; the engine applies no state change.';flags.append(badge);}
    if(pathway.basis){const small=document.createElement('small');small.className='muted';small.textContent=pathway.basis;flags.append(small);}
    if(pathway.uncertainty){const small=document.createElement('small');small.className='muted';small.textContent=pathway.uncertainty;flags.append(small);}
    row.append(flags);body.append(row);
  });
  table.append(body);
  const scroll=document.createElement('div');scroll.className='table-wrap';scroll.append(table);wrap.append(scroll);
  wrap.append(note('Pathways and their strengths are edited in the advanced JSON below. Changing a variant rescales these configured values; it does not make them empirical.'));
  return wrap;
}
function syncDriversFromForm(){
  currentDrivers=[...byId('driversEditor').querySelectorAll('.driver-card')].map(card=>{
    const index=Number(card.dataset.index);const driver=currentDrivers[index]||{};
    const read=field=>card.querySelector(`[data-field="${field}"]`);
    const text=field=>read(field)?.value??'';
    driver.name=text('name')||driver.driver_id;
    driver.category=text('category')||'unspecified';
    driver.active_variant=text('active_variant')||driver.active_variant||'';
    driver.observable_from=Number(read('observable_from')?.value??0);
    driver.priority=Number(read('priority')?.value??50);
    driver.indicator_variable=text('indicator_variable').trim()||null;
    driver.initial_value=Number(read('initial_value')?.value??0);
    driver.description=text('description');
    driver.enabled=read('enabled')?.checked!==false;
    driver.observable_by=[...card.querySelectorAll('[data-observe-agent]:checked')].map(input=>input.dataset.observeAgent);
    const heading=card.querySelector('.agent-card-head h3');if(heading)heading.textContent=driver.name||driver.driver_id;
    return driver;
  });
  driverBox.value=JSON.stringify(currentDrivers,null,2);
}

/* ---------------- driver-variant comparison ---------------- */
async function compareVariants(index){
  const driver=currentDrivers[index];
  const variants=driver.variants||[];
  if(variants.length<2){setStatus('This driver needs at least two variants to compare.',true);return;}
  const baseline=definitionFromForm();
  setProgress(`Preparing ${variants.length} variant runs…`,5);
  const runs=[];
  try{
    for(let i=0;i<variants.length;i++){
      const variant=variants[i];
      const candidate=JSON.parse(JSON.stringify(baseline));
      const target=(candidate.external_drivers||[]).find(item=>item.driver_id===driver.driver_id);
      if(!target)throw new Error(`Driver '${driver.driver_id}' is not present in the current definition. Save your edits first.`);
      target.active_variant=variant.variant_id;target.enabled=true;
      setProgress(`Running variant “${variant.label||variant.variant_id}” (${i+1} of ${variants.length})…`,5+Math.round(85*(i+1)/variants.length));
      runs.push({variant,result:await request('/simulations/preview-run',{method:'POST',body:JSON.stringify(candidate)})});
    }
    renderVariantComparison(driver,runs);
    showWorkspace();
    setProgress(`Compared ${runs.length} variants of “${driver.name}”.`,100);
    setStatus(`Variant comparison complete: ${runs.length} runs`);
    setTimeout(hideProgress,2200);
  }catch(error){
    byId('errors').textContent=error.message;hideProgress();setStatus('Variant comparison failed',true);
  }
}

initHome();
