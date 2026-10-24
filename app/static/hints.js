/* Hover/focus explanations for every builder control. Loaded before app.js. */

const HINT_CONTROL = {
  name:'Documentation only. Names the simulation in the saved list and inside the definition file; the engine never reads it.',
  simId:'The identity used when saving. Saving with the same ID overwrites that simulation; change it to keep both.',
  description:'Documentation only. Travels with the definition and is never read by the engine.',
  horizon:'How many steps the engine advances. Events, triggers and driver points scheduled beyond this time never happen.',
  step:'Time the clock adds per step. Event times are compared against this clock, so a step of 2 means time goes 0, 2, 4.',
  stepUnit:'Label only. Names the unit in the "advance one <unit>" event description and in the trace.',
  decisionPolicy:'Rule-based ranks every choice with the objective scorer. LLM adds a provider call only when scores tie or are missing.',
  llmMaxCalls:'Caps provider calls for the whole run, across every branch. Decisions past the cap fall back to rules and are marked as not model-chosen.',
  llmMaxTokens:'Caps provider tokens for the whole run, across every branch. Leave empty for no limit.',
  forecast:'Turns final world state into the outcome metrics you see in Outcomes, and feeds objectives that cite forecast metrics.',
  policy:'How branches survive after the tree is built. Diversity keeps the most distinct per agent, Limited keeps the best N, Exhaustive keeps everything up to the safety limit.',
  limit:'Read only by the Diversity and Limited policies. Exhaustive ignores this box.',
  safety:'Read only by the Exhaustive policy. Diversity and Limited never look at this box.',
  llmFillGaps:'One provider call before the run. The model may only fill gaps it detects — a value stored as text instead of a number, an agent with no actions, an agent with no decision timing — and never changes what you entered.',
  savedSelect:'Opens a simulation you saved to simulations/. Loading it replaces the current form; unsaved edits are lost.',
  templateSelect:'Bundled examples from examples/. Loading one makes an editable copy with a new ID; the file itself is never overwritten.'
};

const HINT_AGENT_FIELD = {
  internalId:'Read-only identity. Actions, triggers and the decision trace reference the agent by this ID, so renaming the display name above never breaks them.',
  name:'Shown on this card, in the decision trace and on the charts. The engine still matches agents by the internal ID.',
  type:'Stakeholder label sent to the model as part of the agent description. The rule-based scorer ignores it.',
  objective:'Plain-language goal. The model reads this; the rule-based scorer uses the structured evaluation objectives in the advanced JSON instead.'
};
const HINT_TRIGGER_MODE = 'When this agent is asked to decide. "Never" means its actions are configured but never used.';
const HINT_ACTION_TICK = 'Ticks become this agent\u2019s available actions. An action it cannot take never appears in the trace.';
const HINT_OBSERVE_ALL = 'Give the agent every world variable, including ones you add later.';
const HINT_OBSERVATION = 'The agent only sees ticked variables. With nothing ticked the model cannot cite a fact, so its decisions are rejected and made by the rule-based fallback.';
const HINT_DRIVER_OBSERVE = 'Only these agents can read the driver\u2019s indicator variable as an observable fact.';

const HINT_DRIVER_FIELD = {
  name:'Shown on this card and in the driver-effect table; the engine matches drivers by the driver ID in the JSON.',
  category:'Grouping label used in the driver effects, audit records and evidence panel. It does not change behaviour.',
  active_variant:'The trajectory applied in this run. "Compare all variants" re-runs the definition once per variant.',
  observable_from:'Before this time the indicator holds its initial value; from here the variant trajectory applies. A value past the time horizon fails validation.',
  priority:'Order among events that fire at the same time \u2014 higher first.',
  indicator_variable:'A NEW world variable this driver publishes; it must not already exist in step 2. Without it the driver only applies pathways and no agent can observe it.',
  initial_value:'The indicator\u2019s value until observable_from, after which the trajectory levels take over.',
  description:'Documentation shown on the card and carried into the definition. The engine does not read it.',
  enabled:'Off excludes this driver completely: no indicator, no events, no pathway effects. The definition still keeps its configuration.'
};

const HINT_BUILDER = {
  name:'Labels the action on the agent card and in the trace. The action ID is generated from this text.',
  variable:'The world variable this action changes. Only variables listed in step 2 can be chosen.',
  operation:'How the value applies to the variable: replaces it, adds or subtracts, or scales it.',
  value:'The number, true/false, or text used by the operation above.',
  react:'Emits an event named after this action when chosen, so other agents can be triggered by it. Without it, only scheduled and driver events wake agents.'
};

/* Both Driver-Based Forecasting registers are built by script, so each cell holds a bare input with
   no <label> around it: hintForLabel() cannot reach them and the column header's ⓘ is the only
   explanation on screen, several columns away from the box being typed into. Every entry states the
   role, the format and range, and what the model does with the number. */
const HINT_FORECAST_CELL = {
  driver:{
    name:'Identifies this driver in the register, the period table and the contribution columns. Free text; two drivers cannot share a name. The model only uses it to label its output, so renaming a driver changes nothing about the forecast.',
    basis:'Chooses how the index is carried into the projected periods, and this note ends with the rule the model follows for the basis chosen now. Cells the other basis would use are greyed out and never read.',
    levels:'The driver\u2019s index level in each recorded period, oldest first, separated by commas or spaces. Format: two or more plain numbers, no unit and no percent sign \u2014 1 means the pathway fires exactly as configured, 2 means twice as hard. The model fits a least-squares straight line through these readings and continues it into every projected period, scaling the pathway by the index it produces.',
    initial:'The index level at T\u2080, the period the forecast starts from. Format: one plain number; 1 means no scaling at the start. Required on this basis, and the model compounds growth from it every projected period.',
    growth:'Growth of the index per period, typed as a percentage (0\u2013100), not a fraction: 8 means +8% each period, so the index at period k is the anchor multiplied by 1.08 to the power k. Must be above \u2212100% \u2014 a rate of \u2212100% or lower annihilates the index in one period and the forecast is refused. The model uses it to scale the pathway, not to change the variable directly.',
    target:'The affected model variable this pathway moves. Type it exactly as it appears in the register below, or pick it from the list. The model reads this variable\u2019s baseline from that register and refuses the forecast when no row carries this name.',
    operation:'How the pathway value is applied to the variable in every projected period, and this note ends with the rule the model follows for the operation chosen now.',
    magnitude:'The pathway value at index 1.0, in the affected variable\u2019s own unit. Format: one plain number, positive or negative. The model scales add, subtract and multiply by the projected index and applies the result to the variable after its own growth for that period.',
    minimum:'Optional floor, typed in the affected variable\u2019s own unit. Format: one plain number, or blank for no floor. The model clamps the pathway\u2019s result to it and reports the periods where the floor bound.',
    maximum:'Optional ceiling, typed in the affected variable\u2019s own unit. Format: one plain number, or blank for no ceiling. The model clamps the pathway\u2019s result to it and reports the periods where the ceiling bound; it must not sit below the minimum.',
    grade:'How this pathway\u2019s number is justified. The model records it and displays it beside the result; it does not change the arithmetic, so choosing a stronger grade never turns a typed figure into a measurement.',
    hypothesis:'Off by default. Ticked, the model applies no number from this pathway: its index is still projected and shown, but the variable is left untouched and the effect cells grey out. Use it for a driver you are not ready to quantify.'
  },
  variable:{
    name:'The quantity a pathway moves. Free text, and it must match the affected model variable column above exactly, because the model looks the baseline up by this name. Every driver target has to be named here.',
    value:'Required. The value this variable holds at T\u2080, the period the forecast starts from, in the unit beside it. Format: one plain number, not a percentage. The model applies growth and every pathway to this number, so a blank baseline is refused rather than read as zero.',
    unit:'Optional free text saying what one unit of the baseline means, for example “treated patients per quarter” or “market share as a fraction (0\u20131)”. The model converts nothing \u2014 this text only names the quantity, and every result column repeats it.',
    growth:'The variable\u2019s own organic growth per period, applied before any driver effect lands. Typed as a percentage (0\u2013100), not a fraction: 6 is +6% each period and \u22123 is \u22123%. Must be above \u2212100%. Blank means the model applies no organic drift, so the variable only moves when a pathway moves it.'
  }
};

/* A dropdown's meaning depends on the entry selected, so the cell hint appends the current choice. */
const HINT_FORECAST_OPTION = {
  basis:{
    observed:'Observed index values: the model continues a least-squares straight line fitted through the readings in the observed-values cell.',
    compound:'Compound growth: the model grows the T\u2080 anchor geometrically at the growth rate entered here.'
  },
  operation:{
    set:'set: replaces the variable with the magnitude. The index does not scale it, so every period is set to the same level.',
    add:'add: increases the variable by the magnitude multiplied by the projected index.',
    subtract:'subtract: decreases the variable by the magnitude multiplied by the projected index.',
    multiply:'multiply: scales the variable by 1 + (magnitude \u2212 1) \u00d7 index, so magnitude 1.2 at index 1 gives 1.2 times the value.',
    divide:'divide: divides the variable by the magnitude. The index does not scale it, and a magnitude of zero is refused.'
  },
  grade:{
    empirical:'empirical: a reading taken from data.',
    user_assumption:'user assumption: a number you chose and can defend as a working assumption.',
    model_hypothesis:'model hypothesis: a level the model\u2019s structure suggests but no data confirms.',
    synthetic_illustrative:'synthetic illustrative: a placeholder that only shows what the mechanism does \u2014 never present it as evidence.'
  }
};

const HINT_LEGEND = {
  'When this agent decides':'Writes the trigger definitions in step 5 for you. "Custom trigger (advanced JSON)" leaves whatever you configured in that JSON untouched.',
  'Choices this agent can make':'Ticked actions become the agent\u2019s available actions. Build simple ones here, or edit constraints in step 4.',
  'What this agent can observe':'Controls the variables this agent is shown when it decides. Rule-based scores and model rationales can only cite what is visible here.',
  'Which agents can observe the indicator':'Ticked agents are given the driver\u2019s indicator variable as an observable fact when it becomes observable.'
};

const HINT_ADVANCED = {
  agents:'Full agent definitions. The guided cards write here; fields the cards do not show, such as evaluation objectives and decision policies, are used exactly as written.',
  actions:'Action definitions with effects, constraints and generated events. The action builder on each agent card appends to this list.',
  triggers:'When each agent decides. Cooldowns, expiry and state conditions only exist here \u2014 the cards manage the auto-generated start and every-round triggers.',
  drivers:'External driver variants, trajectories and pathways, including per-pathway lag, bounds and evidence grades. The cards edit the fields they show.',
  transitions:'Transition rules: the arithmetic that changes world state when an event fires. Driver pathways compile into rules of the same shape.',
  initialEvents:'Events injected at time 0, before the first step. The bundled examples emit "simulation_start" here; without it, once-at-start agents never wake.',
  scheduledEvents:'Events at fixed times with a priority. The guided builder writes its per-round decision points here.'
};

function hintSpan(text){
  const s=document.createElement('span');
  s.className='hint';s.tabIndex=0;s.dataset.hint=text;s.textContent='i';
  s.setAttribute('aria-label',text);return s;
}
function hintForLabel(label){
  const control=label.querySelector('input,select,textarea');if(!control)return '';
  if(control.id&&HINT_CONTROL[control.id])return HINT_CONTROL[control.id];
  if(control.dataset.triggerMode!==undefined)return HINT_TRIGGER_MODE;
  if(control.dataset.actionId)return HINT_ACTION_TICK;
  if(control.dataset.observeAll)return HINT_OBSERVE_ALL;
  if(control.dataset.observation)return HINT_OBSERVATION;
  if(control.dataset.observeAgent)return HINT_DRIVER_OBSERVE;
  const builder=control.dataset.builderField;if(builder&&HINT_BUILDER[builder])return HINT_BUILDER[builder];
  const field=control.dataset.field;if(!field)return '';
  const card=label.closest('.driver-card')?'driver':'agent';
  const map=card==='driver'?HINT_DRIVER_FIELD:HINT_AGENT_FIELD;
  return map[field]||'';
}
function attachHint(host,text,atEnd){
  if(!text||host.dataset.hintsAttached)return;
  host.dataset.hintsAttached='1';
  const span=hintSpan(text);
  // Buttons and form controls render no child content, so a nested ⓘ would be invisible.
  if(host.matches('button,input,select,textarea')){host.after(span);return;}
  if(atEnd||!(host.firstChild instanceof Text))host.append(span);
  else host.insertBefore(span,host.firstChild.nextSibling);
}
function setFieldHint(node,text){
  node.dataset.hint=text;
  /* The tooltip reads the icon, because the icon is the element under the pointer, so a field whose
     hint changes after its row was built has to repaint its own icon as well. */
  const icon=node.parentElement&&node.parentElement.querySelector('.hint');
  if(icon){icon.dataset.hint=text;icon.setAttribute('aria-label',text);}
}
function attachHints(root){
  const scope=root||document;
  scope.querySelectorAll('[data-hint]:not(.hint)').forEach(el=>attachHint(el,el.dataset.hint,true));
  scope.querySelectorAll('label').forEach(label=>{
    if(label.hasAttribute('data-hint'))return;
    attachHint(label,hintForLabel(label));});
  scope.querySelectorAll('legend').forEach(legend=>
    attachHint(legend,HINT_LEGEND[legend.textContent.trim()],true));
  scope.querySelectorAll('details.advanced').forEach(box=>{
    const area=box.querySelector('textarea'),summary=box.querySelector('summary');
    if(area&&summary)attachHint(summary,HINT_ADVANCED[area.id],true);});
}

/* One shared tooltip, positioned fixed so scroll containers cannot clip it. */
function tipElement(){
  let tip=byId('tip');if(tip)return tip;
  tip=document.createElement('div');tip.id='tip';tip.className='tip';tip.setAttribute('role','tooltip');
  tip.hidden=true;document.body.append(tip);return tip;
}
function showTip(host){
  const tip=tipElement();tip.textContent=host.dataset.hint;tip.hidden=false;
  const r=host.getBoundingClientRect(),t=tip.getBoundingClientRect();
  tip.style.left=`${Math.min(Math.max(8,r.left+r.width/2-t.width/2),window.innerWidth-t.width-8)}px`;
  let top=r.top-t.height-8;if(top<8)top=r.bottom+8;
  if(top+t.height>window.innerHeight-8)top=Math.max(8,window.innerHeight-t.height-8);
  tip.style.top=`${top}px`;
}
function hideTip(){const tip=byId('tip');if(tip)tip.hidden=true;}
document.addEventListener('pointerover',event=>{
  const host=event.target.closest?.('[data-hint]');if(host)showTip(host);});
document.addEventListener('pointerout',event=>{
  if(event.target.closest?.('[data-hint]'))hideTip();});
document.addEventListener('focusin',event=>{
  const host=event.target.closest?.('[data-hint]');if(host)showTip(host);else hideTip();});
document.addEventListener('focusout',hideTip);
document.addEventListener('click',event=>{
  const host=event.target.closest?.('.hint');if(host)event.preventDefault();});
window.addEventListener('scroll',hideTip,true);
window.addEventListener('resize',hideTip);

attachHints();
