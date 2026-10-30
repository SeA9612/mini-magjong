const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(process.env.CLIENT_SCRIPT_PATH || path.join(__dirname, '../web/app.js'), 'utf8');
const styleSource = fs.readFileSync(path.join(__dirname, '../web/style.css'), 'utf8');

function node() {
  const attributes={};
  const item={style:{},children:[],listeners:{},attributes,textContent:'',className:'',hidden:false,
    set innerHTML(value){this.children=[]},
    appendChild(child){this.children.push(child); child.parentElement=this},
    addEventListener(event,fn){this.listeners[event]=fn},
    getAttribute(name){return attributes[name]??null},
    setAttribute(name,value){attributes[name]=String(value)},remove(){}};
  item.classList={
    add(name){if(!item.className.split(/\s+/).includes(name))item.className=`${item.className} ${name}`.trim()},
    remove(name){item.className=item.className.split(/\s+/).filter(value=>value!==name).join(' ')},
    contains(name){return item.className.split(/\s+/).includes(name)}
  };
  return item;
}
const tile = {suit:'z',value:5,code:'5z',is_aka:false,name:'白'};
function state() {
  return {game_id:'test-game',difficulty:'medium',difficulty_target_yaku:['리치','핑후','탕야오','치토이츠'],can_change_difficulty:true,
    revision:0,wall_remaining:95,round_wind:1,current_turn:0,is_game_over:false,
    current_drawn_tile:tile,pending_reaction:null,last_message:'ready',human_waits:[],
    human_turn_actions:{can_riichi:true,riichi_candidates:[tile],kans:[]},
    players:[{seat_wind:1,concealed_tiles:[...Array(13)].map((_,i)=>({...tile,code:'1m',suit:'m',value:1})).concat(tile),melds:[],discards:[]},
             {seat_wind:2,concealed_count:13,melds:[],discards:[]}]};
}
async function load(initial=state(), started=true, storedValue=null) {
  const nodes = new Map();
  const stored = new Map();
  if (storedValue !== null) stored.set('riichi-mahjong.match-history.v1',storedValue);
  const localStorage={getItem(key){return stored.has(key)?stored.get(key):null},setItem(key,value){stored.set(key,String(value))}};
  const document = {getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)},
    createElement:node,querySelectorAll:()=>[],documentElement:{dataset:{}}};
  document.getElementById('start-modal').style.display=started?'none':'flex';
  document.getElementById('game-container').style.visibility=started?'visible':'hidden';
  const context = vm.createContext({document,localStorage,console:{error(...args){throw Error(args.join(' '))},warn(){}},
    fetch:async()=>({ok:true,json:async()=>initial}),setInterval(){},setTimeout(){},confirm:()=>true});
  vm.runInContext(source,context);
  await vm.runInContext('fetchState()',context);
  return {context,nodes,stored};
}
test('older polling response cannot replace newer action state',async()=>{
  const {context}=await load();
  assert.equal(vm.runInContext('acceptState({...gameState,revision:2})',context),true);
  assert.equal(vm.runInContext('acceptState({...gameState,revision:1})',context),false);
  assert.equal(vm.runInContext('gameState.revision',context),2);
});
test('a new or upgraded meld gets a one-time entrance effect only when its state changes',async()=>{
  const {context,nodes}=await load();
  const next=state();
  next.revision=1;
  next.players[0].melds=[{type:'pon',tiles:[tile,tile,tile]}];
  context.nextMeldState=next;
  vm.runInContext('acceptState(nextMeldState)',context);
  vm.runInContext('render()',context);
  assert.match(nodes.get('human-melds').children[0].className,/meld-entry-flash/);
  assert.match(nodes.get('human-melds').children[0].children[0].className,/meld-tile-entry/);

  // sendAction renders again immediately in its finally block; the queued cue must survive it.
  vm.runInContext('render()',context);
  assert.match(nodes.get('human-melds').children[0].className,/meld-entry-flash/);
  assert.match(nodes.get('human-melds').children[0].children[0].className,/meld-tile-entry/);
  vm.runInContext('pendingHumanMeldEffects.get(0).expiresAt = 0; render()',context);
  assert.doesNotMatch(nodes.get('human-melds').children[0].className,/meld-entry-flash/);
  assert.doesNotMatch(nodes.get('human-melds').children[0].children[0].className,/meld-tile-entry/);

  next.revision=2;
  next.players[0].melds[0]={type:'kan',tiles:[tile,tile,tile,tile]};
  vm.runInContext('acceptState(nextMeldState)',context);
  vm.runInContext('render()',context);
  assert.match(nodes.get('human-melds').children[0].children[0].className,/meld-tile-entry/);
});
test('reduced motion does not make an unavailable riichi button look enabled',async()=>{
  const initial=state();
  initial.human_turn_actions.can_riichi=false;
  initial.players[0].melds=[{type:'chi',tiles:[tile,tile,tile]}];
  const {context,nodes}=await load(initial);
  const button=nodes.get('btn-riichi');
  button.style.display='none';
  vm.runInContext('document.documentElement.dataset.reduceActionMotion="true"; render()',context);
  assert.equal(button.disabled,true);
  assert.match(button.className,/entry-motion/);
  const reducedEntryRule=styleSource.match(/:root\[data-reduce-action-motion="true"\] \.entry-motion,[\s\S]*?\{([^}]*)\}/);
  assert.ok(reducedEntryRule);
  assert.doesNotMatch(reducedEntryRule[1],/opacity\s*:/);
  assert.match(styleSource,/\.btn:disabled\s*\{[^}]*opacity:\s*0\.55/);
});
test('double click sends one action with current revision',async()=>{
  const {context}=await load();
  let finish,requests=0,body;
  context.fetch=async(url,options)=>{requests++;body=JSON.parse(options.body);return new Promise(resolve=>finish=()=>resolve({ok:true,json:async()=>({...state(),revision:1})}))};
  const first=vm.runInContext('sendAction({action:"discard",index:0})',context);
  await vm.runInContext('sendAction({action:"discard",index:1})',context);
  assert.equal(requests,1);
  assert.equal(body.revision,0);
  finish(); await first;
  assert.equal(vm.runInContext('isSendingAction',context),false);
});
test('noncandidate click in riichi mode cannot send discard',async()=>{
  const {context,nodes}=await load();
  let requests=0;
  context.fetch=async()=>{requests++;return {ok:true,json:async()=>state()}};
  nodes.get('btn-riichi').listeners.click();
  nodes.get('human-hand-tiles').children[0].listeners.click();
  assert.equal(requests,0);
  assert.match(nodes.get('human-hand-tiles').children[0].className,/locked/);
  nodes.get('btn-riichi').listeners.click();
  assert.equal(nodes.get('btn-riichi').textContent,'리치 선언');
});
test('AI winning result renders concealed tiles and melds',async()=>{
  const initial=state();
  Object.assign(initial,{is_game_over:true,winner:1,winning_type:'tsumo',winning_tile:tile,
    winning_hand:Array(11).fill(tile),winning_melds:[{tiles:Array(3).fill(tile)}],winning_yaku:[{name:'탕야오',romaji:'Tanyao'}]});
  const {nodes}=await load(initial);
  assert.equal(nodes.get('gameover-modal').style.display,'flex');
  assert.equal(nodes.get('turn-indicator').textContent,'대국이 종료되었습니다');
  assert.equal(nodes.get('gameover-hand').children.length,12);
  assert.equal(nodes.get('gameover-hand').children[11].children.length,3);
});
test('ron result does not append winning tile a second time',async()=>{
  const initial=state();
  Object.assign(initial,{is_game_over:true,winner:0,winning_type:'ron',winning_tile:tile,
    winning_hand:Array(14).fill(tile),winning_melds:[],winning_yaku:[]});
  const {nodes}=await load(initial);
  assert.equal(nodes.get('gameover-hand').children.length,14);
});
test('post-call turn leaves drawn slot empty and all tiles in hand',async()=>{
  const initial=state();
  initial.current_drawn_tile=null;
  initial.players[0].concealed_tiles=Array(11).fill(tile);
  const {nodes}=await load(initial);
  assert.equal(nodes.get('human-hand-tiles').children.length,11);
  assert.equal(nodes.get('drawn-tile-slot').children.length,0);
});

test('legacy server without drawn metadata still permits riichi tsumogiri',async()=>{
  const initial=state();
  initial.players[0].is_riichi=true;
  initial.human_turn_actions={can_tsumo:false,kans:[]};
  delete initial.current_drawn_tile;
  delete initial.revision;
  const {context,nodes}=await load(initial);
  assert.equal(nodes.get('human-hand-tiles').children.length,13);
  assert.equal(nodes.get('drawn-tile-slot').children.length,1);
  assert.doesNotMatch(nodes.get('drawn-tile-slot').children[0].className,/locked/);
  assert.ok(nodes.get('human-hand-tiles').children.every(n=>/locked/.test(n.className)));
  let body;
  context.fetch=async(url,options)=>{body=JSON.parse(options.body);return {ok:true,json:async()=>({...initial,revision:1})}};
  nodes.get('btn-tsumogiri').listeners.click();
  assert.equal(body.index,13);
  assert.equal(body.action,'discard');
  await new Promise(setImmediate);
});

test('riichi permits only the drawn slot to discard while standing tiles stay locked',async()=>{
  const initial=state();
  initial.players[0].is_riichi=true;
  const {context,nodes}=await load(initial);
  let body,requests=0;
  context.fetch=async(url,options)=>{requests++;body=JSON.parse(options.body);return {ok:true,json:async()=>({...initial,revision:1})}};
  nodes.get('human-hand-tiles').children[0].listeners.click();
  assert.equal(requests,0);
  nodes.get('drawn-tile-slot').children[0].listeners.click();
  assert.equal(requests,1);
  assert.equal(body.index,13);
  await new Promise(setImmediate);
});

test('authoritative drawn index survives sorting and preserves standing tile indices',async()=>{
  const initial=state();
  initial.players[0].concealed_tiles=[tile,{...tile,code:'2z',value:2},tile];
  initial.current_drawn_index=1;
  initial.current_drawn_tile=initial.players[0].concealed_tiles[1];
  const {context,nodes}=await load(initial);
  assert.match(nodes.get('drawn-tile-slot').children[0].className,/tile-code-2z/);
  let body;
  context.fetch=async(url,options)=>{body=JSON.parse(options.body);return {ok:true,json:async()=>({...initial,revision:1})}};
  nodes.get('human-hand-tiles').children[1].listeners.click();
  assert.equal(body.index,2);
  await new Promise(setImmediate);
});

test('explicitly absent drawn tile cannot be inferred during post-call discard',async()=>{
  const initial=state();
  initial.current_drawn_tile=null;
  initial.must_discard_after_call=true;
  const {nodes}=await load(initial);
  assert.equal(nodes.get('drawn-tile-slot').children.length,0);
});

test('start screen hides table until start is clicked, then shows 14 tiles',async()=>{
  const {nodes}=await load(state(),false);
  assert.equal(nodes.get('game-container').style.visibility,'hidden');
  assert.equal(nodes.get('start-modal').style.display,'flex');
  await nodes.get('btn-start-game').listeners.click();
  assert.equal(nodes.get('start-modal').style.display,'none');
  assert.equal(nodes.get('game-container').style.visibility,'visible');
  assert.equal(nodes.get('human-hand-tiles').children.length + nodes.get('drawn-tile-slot').children.length,14);
});

test('how-to-play button opens and closes the controls and rules panel',async()=>{
  const {nodes}=await load(state(),false);
  const button=nodes.get('btn-how-to-play');
  const panel=nodes.get('how-to-play-panel');
  panel.hidden=true;
  assert.equal(panel.hidden,true);
  button.listeners.click();
  assert.equal(panel.hidden,false);
  assert.equal(button.getAttribute('aria-expanded'),'true');
  button.listeners.click();
  assert.equal(panel.hidden,true);
  assert.equal(button.getAttribute('aria-expanded'),'false');
});

test('pause blocks the turn and resume restores it',async()=>{
  const {nodes}=await load();
  nodes.get('btn-pause').listeners.click();
  assert.equal(nodes.get('pause-modal').style.display,'flex');
  assert.equal(nodes.get('turn-indicator').textContent,'일시정지 중입니다');
  assert.match(nodes.get('human-hand-tiles').children[0].className,/locked/);
  nodes.get('btn-resume').listeners.click();
  assert.equal(nodes.get('pause-modal').style.display,'none');
  assert.equal(nodes.get('turn-indicator').textContent,'당신의 턴입니다');
});

test('win, loss, and draw results are labeled distinctly',async()=>{
  for (const [winner,winningType,expected] of [[0,'tsumo','승리 (Win)'],[1,'ron','패배 (Lose)'],[null,'draw','유 국 (Draw)']]) {
    const initial=state();
    Object.assign(initial,{is_game_over:true,winner,winning_type:winningType,winning_tile:tile,
      winning_hand:Array(14).fill(tile),winning_melds:[],winning_yaku:[]});
    const {nodes}=await load(initial);
    assert.ok(nodes.get('gameover-title').textContent.includes(expected));
  }
});

test('completed results are saved once and survive a new game view',async()=>{
  const complete=state();
  Object.assign(complete,{is_game_over:true,winner:0,winning_type:'tsumo',winning_yaku:[{name:'리치'}]});
  const {context,nodes,stored}=await load(complete);
  const key='riichi-mahjong.match-history.v1';
  let saved=JSON.parse(stored.get(key));
  assert.equal(saved.records.length,1);
  assert.equal(saved.records[0].result,'win');
  assert.deepEqual(saved.records[0].yaku,['리치']);
  vm.runInContext('acceptState({...gameState})',context);
  saved=JSON.parse(stored.get(key));
  assert.equal(saved.records.length,1,'polling the same finished game must not duplicate it');

  const {nodes:reopened}=await load(state(),false,stored.get(key));
  assert.equal(reopened.get('history-count').textContent,'보존 기록: 1');
  assert.match(reopened.get('saved-records-list').children[0].textContent,/승리 · 쯔모 · 리치/);
});

test('empty and corrupt saved data safely use an empty default',async()=>{
  for (const raw of ['', '{broken json', JSON.stringify({version:1,records:[{game_id:'bad'}]})]) {
    const {nodes,stored}=await load(state(),false,raw);
    assert.equal(nodes.get('history-count').textContent,'보존 기록: 0');
    assert.match(stored.get('riichi-mahjong.match-history.v1'),/"records":\[\]/);
  }
});

test('starting a new game does not erase preserved result records',async()=>{
  const record={game_id:'old-game',result:'loss',winning_type:'ron',ended_at:1,yaku:['핑후']};
  const raw=JSON.stringify({version:1,records:[record]});
  const {context,stored}=await load(state(),true,raw);
  context.fetch=async(url,options)=>({ok:true,json:async()=>({...state(),game_id:'new-game',revision:1})});
  await vm.runInContext('sendAction({action:"restart"})',context);
  assert.equal(JSON.parse(stored.get('riichi-mahjong.match-history.v1')).records.length,1);
});

test('difficulty selector updates the game mode and target yaku',async()=>{
  const {context,nodes}=await load();
  let request;
  context.fetch=async(url,options)=>{
    request=JSON.parse(options.body);
    return {ok:true,json:async()=>({...state(),difficulty:'low',difficulty_target_yaku:['리치','핑후'],revision:1})};
  };
  nodes.get('difficulty-select').value='low';
  nodes.get('difficulty-select').listeners.change();
  await new Promise(setImmediate);
  assert.equal(request.action,'set_difficulty');
  assert.equal(request.difficulty,'low');
  assert.equal(nodes.get('difficulty-select').value,'low');
  assert.deepEqual(nodes.get('difficulty-target-yaku').children.map(item=>item.textContent),['리치','핑후']);
});

test('new game returns to setup so the next difficulty can be chosen',async()=>{
  const {context,nodes}=await load();
  context.fetch=async()=>({ok:true,json:async()=>({...state(),revision:1})});
  nodes.get('btn-restart').listeners.click();
  await new Promise(setImmediate);
  assert.equal(nodes.get('start-modal').style.display,'flex');
  assert.equal(nodes.get('game-container').style.visibility,'hidden');
  assert.equal(nodes.get('difficulty-select').value,'medium');
});

test('start remains visible with a retry message if the hand cannot render',async()=>{
  const {context,nodes}=await load(state(),false);
  context.console={error(){}};
  const broken=state();
  broken.players[1].melds=null;
  context.fetch=async()=>({ok:true,json:async()=>broken});
  await nodes.get('btn-start-game').listeners.click();
  assert.equal(nodes.get('start-modal').style.display,'flex');
  assert.equal(nodes.get('game-container').style.visibility,'hidden');
  assert.match(nodes.get('start-error').textContent,/실패/);
  assert.equal(nodes.get('btn-start-game').disabled,false);
  context.fetch=async()=>({ok:true,json:async()=>state()});
  await nodes.get('btn-start-game').listeners.click();
  assert.equal(nodes.get('start-modal').style.display,'none');
  assert.equal(nodes.get('human-hand-tiles').children.length+nodes.get('drawn-tile-slot').children.length,14);
});

test('initial connection failure is retryable and clears the error after recovery',async()=>{
  const {context,nodes}=await load(state(),false);
  context.console={error(){}};
  context.fetch=async()=>{throw new Error('offline')};
  await nodes.get('btn-start-game').listeners.click();
  assert.equal(nodes.get('start-modal').style.display,'flex');
  assert.match(nodes.get('start-error').textContent,/실패/);
  context.fetch=async()=>({ok:true,json:async()=>state()});
  await vm.runInContext('fetchState()',context);
  assert.equal(nodes.get('start-error').textContent,'');
  assert.equal(nodes.get('btn-start-game').textContent,'🀄 게임 시작');
  await nodes.get('btn-start-game').listeners.click();
  assert.equal(nodes.get('game-container').style.visibility,'visible');
});

test('unavailable riichi shows the reason and cannot be toggled',async()=>{
  const initial=state();
  initial.human_turn_actions={can_riichi:false,riichi_unavailable_reason:'텐파이가 아닙니다.',kans:[]};
  const {nodes}=await load(initial);
  assert.equal(nodes.get('btn-riichi').style.display,'inline-block');
  assert.equal(nodes.get('btn-riichi').disabled,true);
  assert.equal(nodes.get('riichi-status').textContent,'텐파이가 아닙니다.');
  nodes.get('btn-riichi').listeners.click();
  assert.equal(nodes.get('btn-riichi').textContent,'리치 선언');
});

test('start screen stays above pending reaction and gameover dialogs',async()=>{
  for(const kind of ['reaction','gameover']) {
    const initial=state();
    if(kind==='reaction') initial.pending_reaction={player_idx:0,target_tile:tile,actions:[{type:'pon',tile}]};
    else Object.assign(initial,{is_game_over:true,winner:1,winning_type:'tsumo',winning_tile:tile,winning_hand:Array(14).fill(tile),winning_melds:[],winning_yaku:[]});
    const {nodes}=await load(initial,false);
    assert.equal(nodes.get('start-modal').style.display,'flex');
    assert.equal(nodes.get(kind==='reaction'?'reaction-modal':'gameover-modal').style.display,'none');
    await nodes.get('btn-start-game').listeners.click();
    assert.equal(nodes.get(kind==='reaction'?'reaction-modal':'gameover-modal').style.display,'flex');
  }
});
