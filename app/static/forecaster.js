/* The three standalone forecasting methods on the home page: Time Series Forecasting,
   Analogue-Based Forecasting and Driver-Based Forecasting.
   Each is its own card with its own route — no method picker. They reuse the run chart and table
   builders so there is one line-drawing implementation, and the shared fit/scale helpers so every
   number here matches the same number produced inside a run. */
let lastProjected = null;
let importedTable = null, importSource = null, importedFile = null, autoLabel = '';
let lastDriverData = null;

function parseSeries(text){return (text||'').split(/[\s,;]+/).filter(Boolean).map(Number);}

/* Formula disclosure prints coefficients, so it needs more digits than a results table does. */
function num(value){
  if(value===null||value===undefined||!Number.isFinite(value))return '—';
  const abs=Math.abs(value);
  if(abs!==0&&(abs<1e-4||abs>=1e7))return value.toExponential(3);
  return String(Number(value.toPrecision(6)));
}

function plural(word,count){return count===1?word:`${word}s`;}

function cadenceWord(){return byId('tsCadence').value||'period';}

function seriesUnit(){return (byId('tsUnit').value||'').trim()||'series units';}

/* A blank or fractional horizon is refused, never defaulted: silently projecting four periods
   because a field was cleared is how an accidental number reaches a decision. */
function horizonOf(id,errors){
  const raw=byId(id).value.trim();
  if(raw===''){errors.textContent='Enter a forecast horizon: how many periods to project. A blank horizon is not treated as any default.';return null;}
  const value=Number(raw);
  if(!Number.isInteger(value)||value<1||value>60){
    errors.textContent='Forecast horizon must be a whole number of periods from 1 to 60.';return null;}
  return value;
}

function syncCadenceLabels(){
  /* The horizon input holds the count, so the label pluralises from what is actually typed
     rather than from the default, which said "periods" while one period was requested. */
  const horizonOfCount=id=>{const value=Number(byId(id).value);return Number.isFinite(value)&&value>0?value:4;};
  const word=cadenceWord();
  byId('tsAheadLabel').textContent=`Forecast horizon (${plural(word,horizonOfCount('tsAhead'))})`;
  const item=storedHistory(byId('raHistory').value);
  const analogue=(item&&(item.cadence||'').trim())||'period';
  byId('raAheadLabel').textContent=`Forecast horizon (${plural(analogue,horizonOfCount('raAhead'))} after the borrowed series ends)`;
}

function metricCard(label,value){
  const card=document.createElement('div');card.className='metric';
  const strong=document.createElement('b');strong.textContent=value;
  const small=document.createElement('span');small.textContent=label;
  card.append(strong,small);return card;
}

function resultHeading(text){
  const heading=document.createElement('h3');heading.textContent=text;return heading;
}

/* The one model-details block every method uses: the formula actually executed, the numbers it
   actually used, and what the method does not do. Written from the response, never hard-coded.
   Notes are taken as many arguments as the caller passes, each either a string or a list: a panel
   once handed a second note as an extra argument, and a three-parameter helper dropped it in silence. */
function formulaBlock(equations,symbols,...notes){
  const details=document.createElement('details');details.className='advanced formula';
  const summary=document.createElement('summary');summary.textContent='How this forecast was calculated';
  details.append(summary);
  const body=document.createElement('div');body.className='formula-body';
  equations.forEach(line=>body.append(Object.assign(document.createElement('code'),{className:'eq',textContent:line})));
  if(symbols.length){
    const list=document.createElement('dl');
    symbols.forEach(([term,meaning])=>list.append(
      Object.assign(document.createElement('dt'),{textContent:term}),
      Object.assign(document.createElement('dd'),{textContent:meaning})));
    body.append(list);}
  notes.flat().forEach(line=>
    body.append(Object.assign(document.createElement('p'),{textContent:line})));
  details.append(body);
  return details;
}

function renderForecast(box,data){
  lastProjected=data;
  byId('tsSaveBtn').disabled=false;
  box.replaceChildren();box.classList.remove('muted');
  const unit=seriesUnit();
  const word=cadenceWord();
  const horizon=plural(word,data.projected.length);
  box.append(resultHeading('Time Series Forecasting — results'));
  const summary=document.createElement('div');summary.className='summary';
  summary.append(
    metricCard(`Observed ${plural(word,data.periods)}`,data.periods),
    metricCard(`First observed value (${unit})`,fmt(data.start)),
    metricCard(`Latest observed value (${unit})`,fmt(data.latest)),
    metricCard(`Fitted trend slope (${unit} per ${word})`,fmt(data.slope)),
    metricCard(`In-sample RMSE (${unit})`,fmt(data.rmse)),
    metricCard(`Forecast after ${data.projected.length} ${horizon} (${unit})`,
      fmt(data.projected[data.projected.length-1])));
  box.append(summary);

  /* Observed, fitted and forecast are three different kinds of number, so they are not put under
     one generic heading: residuals only exist for observed periods, and no forecast has an
     observation beside it. */
  box.append(resultHeading('Observed values and fitted trend'));
  box.append(tableFrom([`Period (${word} index)`,`${unit}, observed`,`${unit}, fitted trend`,
    `Residual (${unit})`],
    data.observed.map((value,index)=>[`t${index}`,fmt(value),fmt(data.fitted[index]),
      fmt(data.residuals[index])])));
  box.append(resultHeading('Forecast values (projected, not observed)'));
  box.append(tableFrom([`Period (${word} index)`,`${unit}, forecast`],
    data.projected.map((value,index)=>[`t${data.observed.length+index}`,fmt(value)])));

  const name=(data.label||'').trim()||'Pasted series';
  const scenario={scenario_id:'history',name:`${name} (observed history)`,
    chartNote:'Value you entered as observed history',
    snapshots:data.observed.map((value,index)=>({time:index,variables:{[name]:value}})),
    forecast:{projections:{[name]:data.projected}}};
  box.append(seriesChart(name,[scenario],{},'end of observed history',
    `forecast: ${horizon} extrapolated from the fitted line`,null,
    {unit,fitted:[{key:'fit',name:'Fitted trend line',color:seriesColor(1),
        note:'Fitted value — the line through your observations, not a reading',
        points:data.fitted.map((value,index)=>({time:index,value}))}],
      projectedNote:'Forecast — an extrapolation of the fitted line, not observed',
      periodWord:word,annotations:[{time:data.observed.length-1,label:'observed history ends'}],
      scenarioKeys:false}));

  box.append(formulaBlock(
    [`ŷ(t) = a + b·t,  a = ${num(data.intercept)},  b = ${num(data.slope)} per ${word}`,
      `RMSE = √( Σ (y(t) − ŷ(t))² ⁄ n ),  n = ${data.periods},  RMSE = ${num(data.rmse)} ${unit}`,
      `forecast(t) = a + b·t  for t = ${data.observed.length} … ${data.observed.length+data.projected.length-1}`],
    [['t',`period index; t0 is the first observed value (${word} basis, counted from the start of the series)`],
      ['y(t)',`the observed value you entered, in ${unit}`],
      ['ŷ(t)',`the fitted line at t, and past the last observation the forecast, in ${unit}`],
      ['a',`fitted intercept — the line's value at t0, in ${unit}`],
      ['b',`fitted slope — the change per ${word}, in ${unit}`]],
    [`Method identifier: ${data.method}. Fitted by ordinary least squares over the period index, in one pass, with no rounding between steps: it is deterministic, so the same values and horizon always produce these same numbers.`,
      'These are the same coefficients the Trend projection forecast model computes inside a run: both call one fit function, so a number produced here equals the number produced there.',
      'Missing periods are not interpolated. Every value you enter is treated as the next consecutive period, so a gap in the file shifts the slope unless the missing row is entered too.',
      'The RMSE is in-sample: it measures how well the line describes the periods it was fitted to. No period was held back and no rolling origin was run, so this panel reports no out-of-sample accuracy and no skill score, because none has been measured.',
      'What this model does not do: it has no seasonality, no causal inputs, no calendar, and no confidence or prediction interval. Past the last observed period the line has no evidence under it — it is an extrapolation of the recent trend, not a prediction.']));
  if(data.projection_below_zero_at)box.append(note(
    `The straight line falls below zero at projected period ${data.projection_below_zero_at}. For a quantity that cannot be negative, the trend has stopped being usable by then.`,'assumption-note'));
  box.append(note('RMSE is the average distance between the observed values and the fitted line, in the series’ own unit: the further the projection reaches, the more of that error it inherits. Nothing here is calibrated against real market or clinical data.'));
}

function clearForecast(box){
  lastProjected=null;
  byId('tsSaveBtn').disabled=true;
  byId('tsSavedNote').textContent='';
  box.replaceChildren();box.classList.add('muted');box.textContent='No forecast was produced.';
}

/* ---------------- import a CSV or Excel file as an observed series ---------------- */
function bytesToBase64(bytes){
  const chunk=32768;let binary='';
  for(let start=0;start<bytes.length;start+=chunk)
    binary+=String.fromCharCode.apply(null,bytes.subarray(start,start+chunk));
  return btoa(binary);
}

function importedFrom(table){
  return `${table.file_name}${table.sheet?` (sheet ${table.sheet})`:''}`;
}

function useColumn(column){
  if(!column||!importedTable)return;
  importSource={file:importedFrom(importedTable),column:`${column.column} “${column.name}”`};
  byId('tsValues').value=column.values.map(value=>String(value)).join(', ');
  const label=byId('tsLabel');
  if(!label.value||label.value===autoLabel){label.value=column.name;autoLabel=column.name;}
  byId('tsImportNote').textContent=
    `Read ${column.points} value${column.points===1?'':'s'} from ${importedFrom(importedTable)}, column ${column.column} (“${column.name}”), rows ${column.first_row}-${column.last_row}.`
    +(column.skipped_in_range?` ${column.skipped_in_range} row${column.skipped_in_range===1?'':'s'} in that range had no number and was skipped: the fit treats the values it read as consecutive periods, so if those rows were real periods the slope is computed over the wrong gaps.`:'')
    +' State the unit and the cadence of this column below — the file itself cannot say whether 158 is patients, thousands of dollars or share.'
    +(importedTable.warnings.length?` ${importedTable.warnings.join(' ')}`:'');
  projectSeries();
}

function renderSheetPicker(table){
  const wrap=byId('tsSheetWrap'),select=byId('tsSheet');
  if(table.sheets.length<2){wrap.hidden=true;return;}
  select.replaceChildren();
  table.sheets.forEach(name=>select.append(new Option(name,name)));
  select.value=table.sheet;
  wrap.hidden=false;
}

async function loadImportedFile(file,sheet){
  const errors=byId('tsErrors');
  errors.textContent='';
  try{
    const bytes=new Uint8Array(await file.arrayBuffer());
    const table=await request('/forecast/import-table',{method:'POST',body:JSON.stringify({
      file_name:file.name,sheet:sheet||'',data:bytesToBase64(bytes)})});
    renderSheetPicker(table);
    importedTable=table;
    const select=byId('tsColumn');
    select.replaceChildren();
    table.columns.forEach((column,index)=>
      select.append(new Option(`Column ${column.column} · ${column.name} (${column.points} points)`,String(index))));
    byId('tsColumnWrap').hidden=false;
    select.value='0';
    useColumn(table.columns[0]);
  }catch(error){
    importedTable=null;
    byId('tsColumnWrap').hidden=true;
    byId('tsSheetWrap').hidden=true;
    errors.textContent=error.message;
  }
}

/* ---------------- save the observed series for the other methods ---------------- */
function historySlug(label){
  const slug=(label||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
  return slug||'pasted-series';
}
async function saveProductHistory(){
  if(!lastProjected)return;
  const button=byId('tsSaveBtn'),note=byId('tsSavedNote');
  button.disabled=true;note.textContent='Saving…';
  try{
    /* Only the observed values are stored. The projected periods stay in this panel, so a
       forecast can never be re-read later as if it were history. */
    const created=await request('/histories',{method:'POST',body:JSON.stringify({
      history_id:`${historySlug(lastProjected.label)}-${String(Date.now()).slice(-6)}`,
      name:(lastProjected.label||'').trim()||'Pasted series',
      description:'',values:lastProjected.observed,variable:'',
      unit:(byId('tsUnit').value||'').trim().slice(0,80),
      cadence:cadenceWord(),
      source:(importSource?`${importSource.file}, column ${importSource.column}`
                       :'entered in the Time Series Forecasting panel').slice(0,200),
      evidence_grade:'user_assumption'})});
    await refreshHistories();
    note.textContent=`Stored as “${created.history_id}” in histories/ — the ${lastProjected.observed.length} observed values only, not the ${lastProjected.projected.length} projected periods. It now appears in Analogue-Based Forecasting below${(byId('tsUnit').value||'').trim()?`, labelled ${byId('tsUnit').value.trim()}`:''}, and selecting the “Stored product history” forecast model in step 1 projects it inside a run.`;
  }catch(error){
    note.textContent='';
    byId('tsErrors').textContent=error.message;
  }finally{button.disabled=false;}
}

async function projectSeries(){
  const errors=byId('tsErrors'),box=byId('tsResult'),button=byId('tsRunBtn');
  errors.textContent='';
  const values=parseSeries(byId('tsValues').value);
  if(values.length<2){errors.textContent='Enter at least two observed values, separated by commas or spaces.';clearForecast(box);return;}
  if(values.some(value=>!Number.isFinite(value))){errors.textContent='Every observed value must be a number.';clearForecast(box);return;}
  const periods_ahead=horizonOf('tsAhead',errors);
  if(periods_ahead===null){clearForecast(box);return;}
  button.disabled=true;
  try{
    const data=await request('/forecast/time-series',{method:'POST',body:JSON.stringify({
      values,periods_ahead,label:byId('tsLabel').value.trim()})});
    renderForecast(box,data);
  }catch(e){
    errors.textContent=e.message;
    clearForecast(box);
  }finally{button.disabled=false;}
}

byId('tsRunBtn').onclick=projectSeries;
byId('tsSaveBtn').onclick=saveProductHistory;
byId('tsCadence').onchange=syncCadenceLabels;
byId('tsValues').addEventListener('keydown',event=>{if(event.key==='Enter')projectSeries();});
byId('tsFile').onchange=event=>{
  const file=event.target.files[0];
  importedFile=file||null;
  byId('tsSheetWrap').hidden=true;
  if(file)loadImportedFile(file,'');
};
byId('tsSheet').onchange=()=>{if(importedFile)loadImportedFile(importedFile,byId('tsSheet').value);};
byId('tsColumn').onchange=()=>{
  if(importedTable)useColumn(importedTable.columns[Number(byId('tsColumn').value)]);
};
byId('tsValues').addEventListener('input',()=>{
  if(!importSource)return;
  importSource=null;
  byId('tsImportNote').textContent='These values were edited by hand, so the imported column is no longer the source of this series.';
});

/* ---------------- the other two methods: analogue-based, driver-based ---------------- */
const PATHWAY_OPERATIONS=['set','add','subtract','multiply','divide'];

/* The stored series list is shared with the builder, so this runs after every history save or delete. */
function syncStandaloneHistories(){fillReferenceOptions();}

function referencePeak(item){
  return typeof item.peak==='number'?item.peak:Math.max(...(item.values||[0]));
}

/* A stored series reaches this panel in two shapes: the list summary carries a point count
   and the recorded peak, while a fetched history carries the values themselves. */
function recordedPeriods(item){
  return Number.isFinite(item.points)?item.points:(item.values||[]).length;
}

function seriesDescription(item){
  const unit=(item.unit||'').trim();
  const cadence=(item.cadence||'').trim();
  return [unit?`in ${unit}`:'unit unstated',
    cadence&&cadence!=='period'?`per ${cadence}`:'per period (cadence unstated)'].join(', ');
}

function fillReferenceOptions(){
  const select=byId('raHistory'),keep=select.value;
  select.replaceChildren();
  if(!storedHistories.length){
    select.append(new Option('No product history is stored yet',''));
    byId('raNote').textContent='Analogue-based forecasting needs a stored series to borrow a shape from. Enter or import values in Time Series Forecasting above and save them as a product history first.';
    syncAnalogueNote();
    return;
  }
  storedHistories.forEach(item=>select.append(new Option(
    `${item.name} · ${seriesDescription(item)} · recorded peak ${fmt(referencePeak(item))}`,item.history_id)));
  select.value=storedHistories.some(item=>item.history_id===keep)?keep:select.firstElementChild.value;
  syncAnalogueNote();
}

/* One multiplier preserves a shape inside one metric; it converts nothing. Naming the borrowed
   series' unit on the peak input is what stops a share being typed against a patient count. */
function syncAnalogueNote(){
  syncCadenceLabels();
  const item=storedHistory(byId('raHistory').value);
  const note=byId('raNote');
  const peakLabel=byId('raPeakLabel');
  peakLabel.textContent=item?`Target peak (${(item.unit||'').trim()||'the reference series’ own unit'})`:'Target peak';
  if(!item){note.textContent='';return;}
  const peak=Number(byId('raPeak').value);
  const recorded=referencePeak(item);
  const unstated=!(item.unit||'').trim();
  if(!Number.isFinite(peak)||peak<=0){
    note.textContent=`The borrowed series is ${item.name}, ${seriesDescription(item)}, reached over ${recordedPeriods(item)} recorded periods and graded ${item.evidence_grade.replaceAll('_',' ')}.`
      +(unstated?' Its unit was never stated, so read the stretch as a shape only: the peak you enter must be in the same metric as this series, because one multiplier cannot turn patients into share or dollars into patients.':'')
      +' Enter the peak this product is expected to reach, in that same unit, to see the stretch.';
    return;
  }
  const factor=peak/recorded;
  note.textContent=`Multiplying ${item.name} by ${fmt(factor)} moves its own peak of ${fmt(recorded)} onto the ${fmt(peak)} you entered${(item.unit||'').trim()?`, in ${item.unit.trim()}`:''}, so every recorded period keeps its relative height. The shape is borrowed from that series; the peak is your assumption, not a measurement.`
    +(unstated?' The reference unit was never stated: this only means anything if the number you entered is in the same metric as the borrowed series, because a factor converts nothing — it cannot turn patients into share.'
              :' Both numbers are in the borrowed series’ own unit: the scaling preserves relative shape and converts nothing else.')
    +(factor===1?' A factor of 1 means you are keeping the reference at its recorded size.':(factor<1?' You are shrinking the borrowed shape, so this product is expected to peak below the reference.':''));
}

function renderAnalogue(box,data){
  box.replaceChildren();box.classList.remove('muted');
  const unit=(data.unit||'').trim()||'series units';
  const word=(data.cadence||'').trim()||'period';
  const horizon=plural(word,data.projected.length);
  const lastRecorded=data.recorded.length-1;
  box.append(resultHeading('Analogue-Based Forecasting — results'));
  const summary=document.createElement('div');summary.className='summary';
  summary.append(
    metricCard('Reference product series',data.label),
    metricCard('Reference metric and unit',`${unit}, per ${word}`),
    metricCard(`Reference recorded peak (${unit})`,fmt(data.recorded_peak)),
    metricCard(`Target peak, entered (${unit})`,fmt(data.peak_target)),
    metricCard('Scaling factor',`${fmt(data.scale)}×`),
    metricCard(`Fitted trend slope (${unit} per ${word})`,fmt(data.slope)),
    metricCard(`In-sample RMSE (${unit})`,fmt(data.rmse)),
    metricCard(`Forecast after ${data.projected.length} ${horizon} (${unit})`,
      fmt(data.projected[data.projected.length-1])));
  box.append(summary);
  box.append(note(`The ramp comes from the stored series “${data.label}” (${data.history_id}), ${data.periods} ${plural(word,data.periods)}, ${unit}`
    +(data.source?` from ${data.source}`:'')+', graded '+data.evidence_grade.replaceAll('_',' ')+'. '
    +data.assumption_label,'assumption-note'));

  box.append(resultHeading('Borrowed shape, rescaled, and forecast'));
  box.append(tableFrom([`Launch-relative period (${word} index)`,
    `Reference series, recorded (${unit})`,`This product, rescaled (${unit})`,
    `Fitted trend (${unit})`,'Data kind'],
    [...data.recorded.map((value,index)=>[`t${index}`,fmt(value),fmt(data.observed[index]),
      fmt(data.fitted[index]),index===lastRecorded?'last recorded period of the borrowed series':'borrowed observation'],
    ),
    ...data.projected.map((value,index)=>[`t${data.recorded.length+index}`,'—','—',fmt(value),
      'projected — not observed'])]));

  /* Both lines are the same metric under different names — the borrowed product as recorded, and this
     product's rescaled shape — so they are drawn as two scenarios of one variable, which keeps the
     recorded and the rescaled series on one axis and one legend. */
  const reference={scenario_id:'reference',name:`${data.label} (recorded, unscaled)`,
    chartNote:'Recorded observation of the reference product',
    snapshots:data.recorded.map((value,index)=>({time:index,variables:{[data.label]:value}})),
    forecast:{projections:{}}};
  const target={scenario_id:'this-product',name:`This product (rescaled shape + forecast)`,
    chartNote:'Rescaled from the borrowed shape — an assumption, not a measurement of this product',
    snapshots:data.observed.map((value,index)=>({time:index,variables:{[data.label]:value}})),
    forecast:{projections:{[data.label]:data.projected}}};
  box.append(seriesChart(data.label,[reference,target],{},'end of borrowed history',
    `forecast: ${horizon} extrapolated from the rescaled shape`,null,
    {unit,fitted:[{key:'fit',name:'Fitted trend line',color:seriesColor(2),
        note:'Fitted value — the line through the rescaled shape, not a reading',
        points:data.fitted.map((value,index)=>({time:index,value}))}],
      projectedNote:'Forecast of the rescaled shape — not observed',
      periodWord:word,
      annotations:[{time:lastRecorded,label:'borrowed series ends'}],
      valueLines:[{value:data.peak_target,label:'target peak'}],
      /* Both lines are named products here, so the internal scenario keys add nothing. */
      scenarioKeys:false}));

  box.append(formulaBlock(
    [`scale factor  f = TargetPeak ÷ ReferencePeak = ${num(data.peak_target)} ÷ ${num(data.recorded_peak)} = ${num(data.scale)}`,
      `rescaled(t) = Reference(t) × f   for every recorded period t`,
      `ŷ(t) = a + b·t,  fitted to rescaled(t),  a = ${num(data.intercept)},  b = ${num(data.slope)} per ${word}`,
      `forecast(t) = a + b·t  for t = ${data.recorded.length} … ${data.recorded.length+data.projected.length-1}`],
    [['Reference(t)',`the borrowed product's recorded value at period t, in ${unit}`],
      ['ReferencePeak',`the highest value in that recorded series (${fmt(data.recorded_peak)} ${unit})`],
      ['TargetPeak',`the peak you entered for this product, in the same ${unit}`],
      ['f',`the one multiplier applied to every period — the only number the target product contributes`],
      ['t',`launch-relative period index: t0 is the first recorded period of the borrowed series, and the horizon starts after its last`],
      ['ŷ(t)',`the fitted line through the rescaled shape, and past the borrowed series the forecast`]],
    [`Method identifier: ${data.method}. Deterministic: the same stored series, peak and horizon always give these same numbers.`,
      'These are the same multiplier and the same fit the Reference product analogue forecast model applies inside a run, so a number produced here equals the number produced there.',
      'The RMSE is in-sample to the rescaled shape: it says how straight the borrowed ramp was, not how well this product will track it. Nothing was held back and no analogue was scored against a later outcome, so no accuracy claim is made.']));
  box.append(note('What this model does not do: it does not compare the two products, adjust for price, indication, launch year or channel, or model saturation. Multiplying one series by one factor preserves relative growth exactly and converts nothing else, so the result is only as good as the claim that these two products launch alike — and it is an extrapolation of a borrowed shape, not a prediction of this product.'));
  if(data.projection_above_entered_peak_at)box.append(note(
    `The linear continuation passes the target peak at projected period ${data.projection_above_entered_peak_at}. An entered peak is a level you claimed, not a ceiling the fit respects: past that period the number is arithmetic on a ramp that was still climbing, and the borrowed shape no longer says anything about it.`,'assumption-note'));
  if(data.projection_below_zero_at)box.append(note(
    `The line falls below zero at projected period ${data.projection_below_zero_at}. For a quantity that cannot be negative, the borrowed shape has stopped being usable by then.`,'assumption-note'));
  box.append(note('Nothing here was compared against a simulation. To measure the scaled shape against what stakeholders actually do, select the Reference product analogue forecast model in step 1 of a simulation.'));
}

async function projectAnalogue(){
  const errors=byId('raErrors'),box=byId('raResult'),button=byId('raRunBtn');
  errors.textContent='';
  const historyId=byId('raHistory').value;
  if(!historyId){errors.textContent='No stored series is available to borrow. Save one in Time Series Forecasting above first.';return;}
  const peak=Number(byId('raPeak').value);
  if(!Number.isFinite(peak)||peak<=0){errors.textContent='Enter a target peak greater than zero, in the borrowed series’ own unit: it is the level the borrowed shape is stretched to.';return;}
  const periods_ahead=horizonOf('raAhead',errors);
  if(periods_ahead===null)return;
  button.disabled=true;
  try{
    const data=await request('/forecast/reference-analogue',{method:'POST',body:JSON.stringify({
      history_id:historyId,peak,periods_ahead})});
    renderAnalogue(box,data);
  }catch(error){
    errors.textContent=error.message;
    box.replaceChildren();box.classList.add('muted');box.textContent='The analogue was not projected.';
  }finally{button.disabled=false;}
}

/* ---------------- driver register: several drivers, each with an index and a pathway ---------------- */
const PATHWAY_GRADES=['empirical','user_assumption','model_hypothesis','synthetic_illustrative'];
const DRIVER_CELLS={name:'name',basis:'basis',levels:'levels',initial:'initial',growth:'growth',
  target:'target',operation:'operation',magnitude:'magnitude',minimum:'minimum',maximum:'maximum',
  grade:'grade',hypothesis:'hypothesis'};

function field(row,key,build){
  const cell=document.createElement('td');
  const node=build();
  node.dataset.field=key;
  cell.append(node);
  /* One index basis at a time, but the unused cells stay in the grid: a hidden cell shifts every
     later input out from under its own header, which is how a value ends up in the wrong field. */
  if(key==='levels')cell.dataset.cell='observed';
  if(key==='initial'||key==='growth')cell.dataset.cell='compound';
  row.append(cell);
  cellHint(node);
  if(HINT_FORECAST_OPTION[key])node.addEventListener('change',()=>cellHint(node));
  return node;
}

/* Explains the box the cursor is in, not just the column it sits under: these registers have no
   <label> per cell, so the header's ⓘ would be several columns away from what is being typed. */
function cellHint(node,reason){
  const map=HINT_FORECAST_CELL[node.closest('tr').dataset.register]||{};
  let text=map[node.dataset.field]||'';
  const choice=HINT_FORECAST_OPTION[node.dataset.field]&&HINT_FORECAST_OPTION[node.dataset.field][node.value];
  if(choice)text+=` Currently: ${choice}`;
  if(reason)text+=` ${reason}`;
  setFieldHint(node,text);
}

function basisText(row){
  const compound=row.querySelector(`[data-field=${DRIVER_CELLS.basis}]`).value==='compound';
  row.querySelectorAll('[data-cell]').forEach(cell=>{
    const unused=cell.dataset.cell!==(compound?'compound':'observed');
    cell.classList.toggle('is-inert',unused);
    const node=cell.querySelector('input,select');
    if(node){
      node.disabled=unused;
      cellHint(node,unused?`Greyed out because this driver uses the ${compound?'compound growth':'observed index values'} basis, so the model never reads this field.`:'');
    }
  });
}

function applyHypothesis(row){
  /* A hypothesis-only pathway applies no number, so its effect cells are switched off rather
     than left editable and silently ignored. The index cells stay live: they are still projected. */
  const only=row.querySelector(`[data-field=${DRIVER_CELLS.hypothesis}]`).checked;
  [DRIVER_CELLS.operation,DRIVER_CELLS.magnitude,DRIVER_CELLS.minimum,DRIVER_CELLS.maximum].forEach(key=>{
    const node=row.querySelector(`[data-field=${key}]`);
    node.disabled=only;
    node.closest('td').classList.toggle('is-inert',only);
    cellHint(node,only?'Switched off because this pathway is marked hypothesis only, so it applies no number to the variable.':'');
  });
}

function addDriverRow(state){
  const row=document.createElement('tr');
  row.dataset.register='driver';
  field(row,'name',()=>text(state&&state.name,'Regulatory pressure'));
  const basis=field(row,'basis',()=>{
    const select=document.createElement('select');
    select.append(new Option('Observed index values','observed'),new Option('Compound growth','compound'));
    select.value=state&&state.basis||'observed';
    select.onchange=()=>basisText(row);
    return select;
  });
  field(row,'levels',()=>text(state&&state.levels,'1, 1.2, 1.5, 1.9'));
  field(row,'initial',()=>number(state&&state.initial,'1'));
  field(row,'growth',()=>number(state&&state.growth,'8'));
  const target=field(row,'target',()=>text(state&&state.target,'price'));
  target.setAttribute('list','dtVariableNames');
  const operation=field(row,'operation',()=>{
    const select=document.createElement('select');
    select.append(...PATHWAY_OPERATIONS.map(name=>new Option(name,name)));
    select.value=(state&&state.operation)||'add';
    return select;
  });
  field(row,'magnitude',()=>number(state&&state.magnitude,'5'));
  field(row,'minimum',()=>number(state&&state.minimum,''));
  field(row,'maximum',()=>number(state&&state.maximum,''));
  const grade=field(row,'grade',()=>{
    const select=document.createElement('select');
    select.append(...PATHWAY_GRADES.map(name=>new Option(name.replaceAll('_',' '),name)));
    select.value=(state&&state.grade)||'user_assumption';
    return select;
  });
  const hypothesisCell=document.createElement('td');
  const hypothesis=document.createElement('input');
  hypothesis.type='checkbox';hypothesis.dataset.field=DRIVER_CELLS.hypothesis;
  hypothesis.checked=!!(state&&state.hypothesis);
  hypothesis.onchange=()=>applyHypothesis(row);
  hypothesisCell.append(hypothesis);row.append(hypothesisCell);
  cellHint(hypothesis);
  const removeCell=document.createElement('td');
  const remove=document.createElement('button');
  remove.className='subtle';remove.type='button';remove.textContent='Remove';
  remove.dataset.hint='Removes this driver and its pathway. A variable no remaining driver targets must also be removed, or the projection is refused.';
  remove.onclick=()=>{row.remove();refreshVariableNames();};
  removeCell.append(remove);row.append(removeCell);
  byId('dtDrivers').append(row);
  basisText(row);
  applyHypothesis(row);
  attachHints(row);
  return row;
}

/* Named for its own register on purpose: these scripts share one global scope, so two top-level
   functions with one name silently replace each other, whichever loads last wins. */
function addDriverVariableRow(state){
  const row=document.createElement('tr');
  row.dataset.register='variable';
  const name=field(row,'name',()=>text(state&&state.name,'price'));
  name.oninput=refreshVariableNames;
  field(row,'value',()=>number(state&&state.value,''));
  field(row,'unit',()=>text(state&&state.unit,'e.g. USD per course, treated patients'));
  field(row,'growth',()=>number(state&&state.growth,'0'));
  const removeCell=document.createElement('td');
  const remove=document.createElement('button');
  remove.className='subtle';remove.type='button';remove.textContent='Remove';
  remove.dataset.hint='Removes this variable, its baseline value and its growth rate. Refused by the projection if a driver still targets it.';
  remove.onclick=()=>{row.remove();refreshVariableNames();};
  removeCell.append(remove);row.append(removeCell);
  byId('dtVariables').append(row);
  refreshVariableNames();
  attachHints(row);
  return row;
}

function text(value,placeholder){
  const input=document.createElement('input');
  input.type='text';input.placeholder=placeholder;
  if(value!==undefined&&value!==null&&value!=='')input.value=value;
  return input;
}

function number(value,placeholder){
  const input=document.createElement('input');
  input.type='number';input.step='any';input.placeholder=placeholder;
  if(value!==undefined&&value!==null&&value!=='')input.value=value;
  return input;
}

function refreshVariableNames(){
  const list=byId('dtVariableNames');
  list.replaceChildren(...variableNames().map(name=>{
    const option=document.createElement('option');option.value=name;return option;
  }));
}

function variableNames(){
  return [...byId('dtVariables').rows].map(row=>row.querySelector('[data-field=name]').value.trim()).filter(Boolean);
}

function readScenario(){
  const variables=[...byId('dtVariables').rows].map(row=>({
    name:row.querySelector('[data-field=name]').value.trim(),
    value:row.querySelector('[data-field=value]').value,
    unit:row.querySelector('[data-field=unit]').value.trim(),
    growth:row.querySelector('[data-field=growth]').value}));
  const drivers=[...byId('dtDrivers').rows].map(row=>({
    name:row.querySelector(`[data-field=${DRIVER_CELLS.name}]`).value.trim(),
    basis:row.querySelector(`[data-field=${DRIVER_CELLS.basis}]`).value,
    levelsText:row.querySelector(`[data-field=${DRIVER_CELLS.levels}]`).value,
    initial:row.querySelector(`[data-field=${DRIVER_CELLS.initial}]`).value,
    growth:row.querySelector(`[data-field=${DRIVER_CELLS.growth}]`).value,
    target:row.querySelector(`[data-field=${DRIVER_CELLS.target}]`).value.trim(),
    operation:row.querySelector(`[data-field=${DRIVER_CELLS.operation}]`).value,
    magnitude:row.querySelector(`[data-field=${DRIVER_CELLS.magnitude}]`).value,
    minimum:row.querySelector(`[data-field=${DRIVER_CELLS.minimum}]`).value,
    maximum:row.querySelector(`[data-field=${DRIVER_CELLS.maximum}]`).value,
    grade:row.querySelector(`[data-field=${DRIVER_CELLS.grade}]`).value,
    hypothesis:row.querySelector(`[data-field=${DRIVER_CELLS.hypothesis}]`).checked}));
  return {drivers,variables};
}

function scenarioError(scenario){
  const names=scenario.variables.map(item=>item.name);
  if(!scenario.drivers.length)return 'Add at least one external driver: a projection needs an outside force to carry forward.';
  if(!scenario.variables.length)return 'Add at least one affected variable: a pathway must name the quantity it moves.';
  if(new Set(names.map(name=>name.toLowerCase())).size!==names.length)
    return 'Variable names must be unique, or the result cannot say which baseline moved.';
  if(names.some(name=>!name))return 'Every affected variable needs a name.';
  const blank=scenario.variables.find(item=>item.value==='');
  if(blank)return `Variable “${blank.name}”: enter its baseline value at the forecast start. A blank baseline is not read as zero.`;
  if(scenario.variables.some(item=>!Number.isFinite(Number(item.value))))
    return 'Every variable baseline must be a number.';
  if(scenario.variables.some(item=>item.growth!==''&&!Number.isFinite(Number(item.growth))))
    return 'Every variable growth rate must be a percentage number, or left blank for no organic drift.';
  const annihilated=scenario.variables.find(item=>item.growth!==''&&Number(item.growth)<=-100);
  if(annihilated)
    return `Variable “${annihilated.name}”: a growth rate of -100% or below wipes it out in one period. Enter a smaller decline, or set its baseline value to zero.`;
  const seen=new Set();
  for(const driver of scenario.drivers){
    if(!driver.name)return 'Every external driver needs a name; effects are attributed by it.';
    if(seen.has(driver.name.toLowerCase()))return `Driver name “${driver.name}” is used twice.`;
    seen.add(driver.name.toLowerCase());
    if(!driver.target)return `Driver “${driver.name}” has no target variable.`;
    if(!names.includes(driver.target))
      return `Driver “${driver.name}” targets “${driver.target}”, which is not in the affected-variable register. Add it there, or point the pathway at a listed variable.`;
    if(!driver.hypothesis){
      const magnitude=Number(driver.magnitude);
      if(driver.magnitude===''||!Number.isFinite(magnitude))
        return `Driver “${driver.name}”: enter the effect magnitude, or mark the pathway hypothesis only.`;
      if(driver.operation==='divide'&&magnitude===0)
        return `Driver “${driver.name}”: a divide pathway cannot have a magnitude of zero.`;
      const minimum=driver.minimum===''?null:Number(driver.minimum);
      const maximum=driver.maximum===''?null:Number(driver.maximum);
      if(minimum!==null&&!Number.isFinite(minimum))
        return `Driver “${driver.name}”: the minimum allowed value must be a number, or be left empty for no floor.`;
      if(maximum!==null&&!Number.isFinite(maximum))
        return `Driver “${driver.name}”: the maximum allowed value must be a number, or be left empty for no ceiling.`;
      if(minimum!==null&&maximum!==null&&minimum>maximum)
        return `Driver “${driver.name}”: the minimum allowed value cannot be above the maximum allowed value.`;
    }
    if(driver.basis==='observed'){
      const levels=parseSeries(driver.levelsText);
      if(levels.length<2)return `Driver “${driver.name}” continues its own index readings: enter at least two, oldest first, or switch the index basis to compound growth.`;
      if(levels.some(level=>!Number.isFinite(level)))return `Driver “${driver.name}”: every observed driver-index value must be a number.`;
    }else{
      if(driver.initial==='')return `Driver “${driver.name}”: a compound index basis needs the driver index at the forecast start.`;
      if(!Number.isFinite(Number(driver.initial)))return `Driver “${driver.name}”: the driver index at the forecast start must be a number.`;
      if(driver.growth==='')return `Driver “${driver.name}”: a compound index basis needs a growth rate per period.`;
      if(!Number.isFinite(Number(driver.growth)))return `Driver “${driver.name}”: the driver growth rate per period must be a number.`;
      if(Number(driver.growth)<=-100)return `Driver “${driver.name}”: a growth rate of -100% or below annihilates the index in one period. Lower the index level instead.`;
    }
  }
  const inert=scenario.variables.filter(item=>{
    const drifts=item.growth!==''&&Number(item.growth)!==0;
    const moved=scenario.drivers.some(driver=>driver.target.toLowerCase()===item.name.toLowerCase());
    return !drifts&&!moved;});
  if(inert.length)return `Variable “${inert[0].name}” has a baseline but no driver pathway targets it and no growth rate of its own, so it cannot move. Remove it, give it a growth rate, or add a driver for it.`;
  return '';
}

function buildScenario(scenario){
  return {
    drivers:scenario.drivers.map(driver=>{
      const levels=driver.basis==='observed'?parseSeries(driver.levelsText):[];
      return {
        name:driver.name,basis:driver.basis,levels,
        initial_level:driver.basis==='compound'?Number(driver.initial):null,
        growth_rate:driver.basis==='compound'?Number(driver.growth)/100:null,
        pathway:{target_variable:driver.target,operation:driver.hypothesis?'add':driver.operation,
                 value:driver.hypothesis?0:Number(driver.magnitude),
                 minimum:driver.hypothesis||driver.minimum===''?null:Number(driver.minimum),
                 maximum:driver.hypothesis||driver.maximum===''?null:Number(driver.maximum),
                 evidence_grade:driver.grade,qualitative_only:driver.hypothesis}};
    }),
    variables:scenario.variables.map(item=>({name:item.name,value:Number(item.value),unit:item.unit,
      growth_rate:item.growth===''?null:Number(item.growth)/100})),
    periods_ahead:Number(byId('dtAhead').value)};
}

function boundsText(pathway){
  const parts=[];
  if(pathway.minimum!==null&&pathway.minimum!==undefined)parts.push(`minimum ${fmt(pathway.minimum)}`);
  if(pathway.maximum!==null&&pathway.maximum!==undefined)parts.push(`maximum ${fmt(pathway.maximum)}`);
  return parts.length?parts.join(' and '):'unbounded';
}

function pct(value){
  return value===null||value===undefined||!Number.isFinite(value)?'—':`${value>=0?'+':''}${fmt(value*100)}%`;
}

function round(value){
  /* A perfect least-squares fit leaves floating-point dust like 1.1e-16; reported as a residual
     error that reads like a real error, so anything that small is shown as zero. */
  return Math.abs(value)<1e-9?0:value;
}

function unitOf(item){
  return (item.unit||'').trim()||'units unstated';
}

function renderDriver(box,data){
  box.replaceChildren();box.classList.remove('muted');
  lastDriverData=data;
  box.append(resultHeading('Driver-Based Forecasting — results'));
  const summary=document.createElement('div');summary.className='summary';
  summary.append(
    metricCard('External drivers',data.drivers.length),
    metricCard('Affected variables',data.variables.length),
    metricCard('Forecast horizon',`${data.periods_ahead} period${data.periods_ahead===1?'':'s'}`),
    ...data.variables.map(item=>metricCard(`${item.name} at end of horizon (${unitOf(item)})`,
      fmt(item.projected[item.projected.length-1]))),
    ...data.variables.map(item=>metricCard(`${item.name} net change (${unitOf(item)})`,
      fmt(item.change_from_baseline[item.change_from_baseline.length-1]))));
  box.append(summary);

  box.append(resultHeading('External drivers and their pathways'));
  box.append(tableFrom(['External driver','Index basis','Driver index at forecast start',
    'Driver growth per period (%)','Fitted index slope','Index fit RMSE','Implied compound growth',
    'Affected model variable','Effect operation','Effect magnitude','Bounds',
    'Net effect on target','Evidence quality/grade'],
    data.drivers.map(driver=>[driver.name,
      driver.index_basis==='observed'?'Observed index values':'Compound growth',
      fmt(driver.index_at_t0),
      driver.index_basis==='compound'?pct(driver.growth_rate):'—',
      driver.level_slope===null||driver.level_slope===undefined?'—':fmt(round(driver.level_slope)),
      driver.level_rmse===null||driver.level_rmse===undefined?'—':fmt(round(driver.level_rmse)),
      driver.implied_growth_rate===null||driver.implied_growth_rate===undefined?'—':pct(driver.implied_growth_rate),
      driver.target_variable,driver.pathway.operation,fmt(driver.pathway.magnitude),
      boundsText(driver.pathway),
      fmt(driver.contributions.reduce((total,value)=>total+value,0)),
      driver.qualitative_only?'hypothesis only':gradeBadge(driver.pathway.evidence_grade)])));

  box.append(resultHeading('Affected variables'));
  box.append(tableFrom(['Model variable','Baseline value at forecast start','Unit',
    'Variable growth per period (%)','Organic change by end of horizon','Net driver effect',
    'Total change','Drivers applied'],
    data.variables.map(item=>[item.name,fmt(item.baseline),unitOf(item),pct(item.growth_rate),
      fmt(item.organic_change[data.periods_ahead-1]),fmt(item.driver_effect[data.periods_ahead-1]),
      fmt(item.change_from_baseline[data.periods_ahead-1]),
      item.drivers.length?item.drivers.join(', '):'none — organic growth only'])));

  box.append(resultHeading('Period by period'));
  const headers=['Period',...data.drivers.map(driver=>`${driver.name} index`),
    ...data.drivers.map(driver=>`${driver.name} applied effect`),
    ...data.variables.map(item=>`${item.name} value`),
    ...data.variables.map(item=>`${item.name} change from start`)];
  const rows=[[`t₀ (forecast start)`,
    ...data.drivers.map(driver=>fmt(driver.index_at_t0)),
    ...data.drivers.map(()=>'no effect yet'),
    ...data.variables.map(item=>fmt(item.baseline)),
    ...data.variables.map(()=>fmt(0))]];
  for(let step=0;step<data.periods_ahead;step+=1){
    rows.push([`t${step+1}`,...data.drivers.map(driver=>fmt(driver.levels_projected[step])),
      ...data.drivers.map(driver=>driver.applied_values[step]===null
        ?'no numeric effect':fmt(driver.applied_values[step])),
      ...data.variables.map(item=>fmt(item.projected[step])),
      ...data.variables.map(item=>fmt(item.change_from_baseline[step]))]);
  }
  box.append(note('Index is the driver’s projected level; the applied effect is the pathway value after that index scales it. '
    +'Each variable first compounds at its own growth rate, then every pathway targeting it is applied in the order listed below. '
    +'Values are in each variable’s own unit. Select any period — here or on a chart — to see what happened in it.','field-note'));
  const periodTable=tableFrom(headers,rows);
  [...periodTable.querySelectorAll('tbody tr')].forEach((tr,index)=>{
    tr.tabIndex=0;tr.dataset.hint='Shows which driver index, operation and effect produced this period’s values.';
    const reveal=()=>showPeriod(data,index);
    tr.onclick=reveal;tr.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();reveal();}};});
  box.append(periodTable);
  const detail=document.createElement('div');detail.id='dtPeriodDetail';
  detail.className='muted';detail.textContent='Select a period row or a chart point to see the driver index, the operation applied, and the assumptions behind that period.';
  box.append(detail);

  box.append(resultHeading('Driver index paths'));
  data.drivers.forEach(driver=>{
    const seriesName=`${driver.name} index`;
    const observed=driver.levels_observed.map((value,index)=>({time:index,value}));
    const snapshots=observed.length?observed.map(point=>({time:point.time,variables:{[seriesName]:point.value}}))
      :[{time:0,variables:{[seriesName]:driver.index_at_t0}}];
    const scenario={scenario_id:driver.name,name:`${driver.name} (index)`,
      chartNote:observed.length?'Index reading you entered':'Index level you anchored at t₀',snapshots,
      forecast:{projections:{[seriesName]:driver.levels_projected}}};
    const options={unit:'index (1.0 = pathway as configured)',
      projectedNote:'Projected index — arithmetic on the declared basis, not a reading',
      annotations:[{time:driver.index_at_t0!==null&&observed.length?observed.length-1:0,
        label:'index at forecast start'}],
      onSelect:info=>showPeriod(data,info.projected?info.time-(observed.length||1)+1:0),
      scenarioKeys:false};
    if(driver.levels_fitted.length>1)options.fitted=[{key:`fit:${driver.name}`,name:'Fitted index line',
      color:seriesColor(1),note:'Fitted through the readings you entered — not a reading itself',
      points:driver.levels_fitted.map((value,index)=>({time:index,value}))}];
    box.append(seriesChart(seriesName,[scenario],{},'end of observed index',
      'projected index, carrying the pathway',observed.length?null:1,options));
  });

  box.append(resultHeading('Affected variable paths'));
  /* The period axis here is the forecast's own: t0 is the baseline you entered and t1…tN are the
     projected periods, so a point on these charts and the row in the period table say the same thing.
     Nothing before t0 is drawn, because nothing was observed — repeating the baseline across a fake
     history would only make one number look like a series. */
  data.variables.forEach(item=>{
    const anchor=[{time:0,variables:{[item.name]:item.baseline}}];
    const entered='Baseline value you entered at t₀';
    const scenarios=[{scenario_id:'organic',name:'Organic growth only',chartNote:entered,snapshots:anchor,
      forecast:{projections:{[item.name]:item.organic_series.slice(1)}}}];
    const moved=item.driver_effect.some(value=>Math.abs(value)>1e-9);
    if(moved)scenarios.push({scenario_id:item.name,chartNote:entered,
      name:'Organic growth + pathways',snapshots:anchor,
      forecast:{projections:{[item.name]:item.projected}}});
    const caption=item.growth_rate?(moved?'grown at its own rate, then moved by the pathways'
                                        :'grown at its own declared rate, with no pathway on it')
                                 :'moved by the projected pathways';
    box.append(seriesChart(item.name,scenarios,{},'forecast start',caption,null,
      {unit:unitOf(item),projectedNote:'Projected period — computed, not observed',
        annotations:[{time:0,label:'baseline entered (t₀)'}],
        onSelect:info=>showPeriod(data,info.time),scenarioKeys:false}));
  });

  box.append(formulaBlock(
    [...driverEquations(data),...variableEquations(data)],
    [['t',`projected period index: t0 is the forecast start, the period whose baseline you entered`],
      ['I(t)',`the driver's index at period t — a pathway's strength multiplier, dimensionless, 1.0 means the pathway fires exactly as configured`],
      ['V(t)',`the affected variable's value at the end of period t, in that variable's own unit`],
      ['g',`a growth rate per period, entered as a percentage and applied as a decimal fraction`]],
    [`Method identifier: ${data.method}. Deterministic: the same drivers, baselines and horizon always produce these same numbers, in this same application order.`,
      'Where a driver index is fitted to readings you entered, its fit RMSE is in-sample to those readings. No reading was held back and no driver was scored against a later outcome, so this panel reports no forecast accuracy and no skill score, because none has been measured.']));
  box.append(note('What this method does not do: it is not a simulation. No payer, physician, patient or competitor decided anything here, no feedback from an affected variable changed a driver, and a pathway fires in every projected period whether or not its trajectory would still be running. Inside a run, those are the differences.','field-note'));

  box.append(note(`Application order in every projected period: ${data.application_order.join(', then ')}. `
    +'Where two pathways target one variable, that order decides how the change splits between them, exactly as the '
    +'engine’s event ordering decides it inside a run.','assumption-note'));
  if(data.shared_targets.length)data.shared_targets.forEach(item=>box.append(note(
    `${item.variable} is moved by ${item.drivers.join(' and ')}; the “net effect on target” column attributes each driver the change it caused in that order, so the column sums are the total change. Reordering the rows would redistribute the attribution.`,'assumption-note')));
  if(data.hypotheses.length)box.append(note(
    `${data.hypotheses.join(', ')} ${data.hypotheses.length===1?'is':'are'} marked hypothesis only: ${data.hypotheses.length===1?'its':'their'} index is projected and reported, but no numeric effect was applied — the same rule a qualitative-only pathway follows in a run.`,'assumption-note'));
  data.drivers.filter(driver=>driver.bounded_steps.length).forEach(driver=>box.append(note(
    `${driver.name}’s ${boundsText(driver.pathway)} bound in projected period${driver.bounded_steps.length===1?'':'s'} ${driver.bounded_steps.join(', ')}: the pathway would have moved ${driver.target_variable} past it, so the clamp held the value.`,'assumption-note')));
  data.variables.filter(item=>item.below_zero_at).forEach(item=>box.append(note(
    `${item.name} falls below zero at projected period ${item.below_zero_at}. For a quantity that cannot be negative, set a minimum allowed value on the pathway instead of reading that number.`,'assumption-note')));
  box.append(note('Only the exogenous environment and the growth rates you declared moved here. Nothing is evidence: recorded separately for each pathway is the quality grade you gave it.'));
}

/* Every equation the projection actually used, printed from the response it describes. */
function driverEquations(data){
  const lines=[];
  data.drivers.forEach(driver=>{
    if(driver.index_basis==='observed'){
      lines.push(`${driver.name}: I(t) = a + b·t over its ${driver.levels_observed.length} readings, a = ${num(driver.level_intercept)}, b = ${num(round(driver.level_slope))} per period`);
    }else{
      const rate=Number(driver.growth_rate);
      lines.push(`${driver.name}: I(t) = ${num(driver.index_at_t0)} × (1 ${rate<0?'−':'+'} ${num(Math.abs(rate))})^t, so I(1) = ${num(driver.levels_projected[0])}`);
    }
    if(driver.qualitative_only){
      lines.push(`${driver.name}: hypothesis only — no numeric effect, V(t) unchanged by it`);
      return;
    }
    lines.push(`${driver.name} → ${driver.target_variable}: ${scaleRule(driver.pathway.operation,driver.pathway.magnitude)}`);
  });
  return lines;
}

function variableEquations(data){
  const lines=[];
  data.variables.forEach(item=>{
    const rate=Number(item.growth_rate);
    lines.push(`${item.name}: V(t) = [ V(t−1) × (1 ${rate<0?'−':'+'} ${num(Math.abs(rate))}) then each pathway in order ] , V(0) = ${num(item.baseline)} ${unitOf(item)}`);
  });
  lines.push('effect scaling: add/subtract → configured value × I(t);  multiply → 1 + (configured value − 1) × I(t);  set/divide → used as typed, not scaled');
  lines.push('then clamp: V = min(max(V, pathway minimum), pathway maximum), only where a bound was entered');
  return lines;
}

function scaleRule(operation,magnitude){
  const value=num(magnitude);
  if(operation==='add')return `value applied = ${value} × I(t), added to the variable`;
  if(operation==='subtract')return `value applied = ${value} × I(t), subtracted from the variable`;
  if(operation==='multiply')return `value applied = 1 + (${value} − 1) × I(t), the variable is multiplied by it`;
  if(operation==='set')return `variable is set to ${value}, unscaled by the index`;
  return `variable is divided by ${value}, unscaled by the index`;
}

function showPeriod(data,index){
  const box=byId('dtPeriodDetail');
  if(!box)return;
  if(index<0||index>data.periods_ahead)return;
  const step=index-1;
  box.replaceChildren();box.classList.remove('muted');
  box.append(Object.assign(document.createElement('h4'),
    {textContent:index===0?'Period t₀ — the forecast start':`Period t${index} — the ${ordinal(index)} projected period`}));
  const rows=data.drivers.map(driver=>{
    const level=index===0?driver.index_at_t0:driver.levels_projected[step];
    const applied=index===0?null:driver.applied_values[step];
    const contribution=index===0?0:driver.contributions[step];
    return [driver.name,fmt(level),
      driver.qualitative_only?'hypothesis only':driver.pathway.operation,
      applied===null?'no numeric effect':fmt(applied),
      `${contribution>=0?'+':''}${fmt(contribution)} on ${driver.target_variable}`,
      boundsText(driver.pathway)+(driver.bounded_steps.includes(index)?' — binding in this period':''),
      driver.qualitative_only?'hypothesis only':driver.pathway.evidence_grade.replaceAll('_',' ')];});
  box.append(tableFrom(['External driver','Index at this period','Effect operation',
    'Applied value','Change this driver caused','Bounds','Evidence quality/grade'],rows));
  const variables=data.variables.map(item=>[item.name,fmt(item.baseline),
    index===0?fmt(item.baseline):fmt(item.organic_series[index]),
    index===0?'—':fmt(item.projected[step]),
    index===0?fmt(0):fmt(item.change_from_baseline[step]),
    unitOf(item)]);
  box.append(tableFrom(['Model variable','Baseline at start','Organic drift only','After pathways',
    'Total change','Unit'],variables));
  box.append(note(index===0
    ?'No pathway has fired yet: this is the environment as entered, with each variable at the baseline you typed.'
    :`Organic drift compounds first, then the drivers act in the order ${data.application_order.join(', then ')}. The two change columns add up to the total change by construction.`,'field-note'));
}

function ordinal(n){
  const suffix=n%10===1&&n%100!==11?'st':n%10===2&&n%100!==12?'nd':n%10===3&&n%100!==13?'rd':'th';
  return n+suffix;
}

async function projectDriver(){
  const errors=byId('dtErrors'),box=byId('dtResult'),button=byId('dtRunBtn');
  errors.textContent='';
  const scenario=readScenario();
  const problem=scenarioError(scenario);
  if(problem){errors.textContent=problem;clearDriver(box);return;}
  const periods_ahead=horizonOf('dtAhead',errors);
  if(periods_ahead===null){clearDriver(box);return;}
  button.disabled=true;
  try{
    const data=await request('/forecast/driver-scenario',{method:'POST',
      body:JSON.stringify(buildScenario(scenario))});
    renderDriver(box,data);
  }catch(error){
    errors.textContent=error.message;
    clearDriver(box);
  }finally{button.disabled=false;}
}

function clearDriver(box){
  lastDriverData=null;
  box.replaceChildren();box.classList.add('muted');box.textContent='The forecast was not produced.';
}

async function loadDriverTable(file){
  const errors=byId('dtErrors');
  errors.textContent='';
  try{
    const table=await readTable(file);
    const fresh=table.columns.map(column=>({name:column.name,basis:'observed',
      levels:column.values.map(value=>String(value)).join(', ')}));
    byId('dtDrivers').replaceChildren();
    fresh.forEach(state=>addDriverRow(state));
    byId('dtImportNote').textContent=
      `Read ${fresh.length} driver${fresh.length===1?'':'s'} from ${table.file_name}`
      +(table.sheet?` (sheet ${table.sheet})`:'')+
      '. Each column header became a driver name and its numbers the observed driver-index values, so set the variable each one moves, the effect operation and the magnitude. '
      +(table.warnings.length?table.warnings.join(' '):'');
  }catch(error){
    errors.textContent=error.message;
  }
}

async function readTable(file){
  const bytes=new Uint8Array(await file.arrayBuffer());
  return request('/forecast/import-table',{method:'POST',body:JSON.stringify({
    file_name:file.name,sheet:'',data:bytesToBase64(bytes)})});
}

function columnMatch(columns,pattern){
  return columns.find(column=>pattern.test(column.name.replace(/[^a-z0-9]/gi,'').toLowerCase()));
}

async function loadVariableTable(file){
  const errors=byId('dtErrors');
  errors.textContent='';
  try{
    const table=await readTable(file);
    /* A text first column is only a name column if it says so: the same shape carries period
       labels in a series file, and reading "Q1" as a variable would invent an entry from a date. */
    const named=table.label_column&&/variable|name|item|entry|metric|quantity/i
      .test(table.label_column.name.replace(/[^a-z]/gi,'').toLowerCase());
    if(!named)throw new Error(`${table.file_name} has no variable-name column. Put one variable per row `
      +'with the names in the first column, headed “Variable” or “Name”, then a value column and an optional growth rate column.');
    const numeric=table.columns;
    const names=table.label_column.values;
    const unitColumn=table.columns.find(column=>/unit|uom/i.test(column.name))
      ||(table.text_columns||[]).find(column=>/unit|uom/i.test(column.name));
    const growth=columnMatch(numeric,/growth|rate|cagr|drift/i);
    const value=columnMatch(numeric.filter(item=>item!==growth),/value|baseline|t0|t_0|current|level|qty|quantity/i)
      ||numeric.find(item=>item!==growth);
    if(!value)throw new Error(`${table.file_name} has a name column but no value column to read the baselines from.`);
    /* A growth column is read as a percentage when any number in it is bigger than one, because
       6 beside 0.05 cannot mean six hundred percent; when every number is within ±1 it is taken
       as the decimal rate itself. Either way the reading applied is reported below. */
    const asPercent=growth&&growth.values.some(sample=>Math.abs(sample)>1);
    const fresh=names.map((name,index)=>({name:name||`Row ${index+2}`,value:value.values[index],
      unit:unitColumn&&unitColumn.values[index]?String(unitColumn.values[index]):'',
      growth:growth&&growth.values[index]!==undefined
        ?(asPercent?growth.values[index]/100:growth.values[index])*100:''}));
    const missing=fresh.filter(item=>item.value===undefined).map(item=>item.name);
    byId('dtVariables').replaceChildren();
    fresh.forEach(state=>addDriverVariableRow(state));
    byId('dtImportNote').textContent=
      `Read ${fresh.length} variable${fresh.length===1?'':'s'} from ${table.file_name}`
      +(table.sheet?` (sheet ${table.sheet})`:'')
      +(growth?`; growth rates taken from “${growth.name}” as ${asPercent?'percentages':'decimals per period'}`
              :'; no growth rate column was found, so every variable starts with no organic drift')
      +(unitColumn?`; units taken from “${unitColumn.name}”`:'; no unit column was found, so each variable’s unit stays unstated until you type it')
      +(missing.length?`. ${missing.join(', ')} had no number in the value column and is left blank — the projection refuses until it is filled in, because a blank baseline is not zero`:'')
      +'. Set each one as the forecast’s starting point; drivers act on top of this drift. '
      +(table.warnings.length?table.warnings.join(' '):'');
  }catch(error){
    errors.textContent=error.message;
  }
}

byId('raHistory').onchange=syncAnalogueNote;
byId('raPeak').addEventListener('input',syncAnalogueNote);
byId('raRunBtn').onclick=projectAnalogue;
byId('dtAddDriver').onclick=()=>{addDriverRow();refreshVariableNames();};
byId('dtAddVariable').onclick=()=>addDriverVariableRow();
byId('dtRunBtn').onclick=projectDriver;
byId('dtFile').onchange=event=>{const file=event.target.files[0];if(file)loadDriverTable(file);};
byId('dtVarFile').onchange=event=>{const file=event.target.files[0];if(file)loadVariableTable(file);};
addDriverRow();
addDriverVariableRow();
syncCadenceLabels();
