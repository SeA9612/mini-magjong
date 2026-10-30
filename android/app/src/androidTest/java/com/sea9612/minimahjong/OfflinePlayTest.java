package com.sea9612.minimahjong;

import android.app.Instrumentation;
import android.content.Intent;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import android.view.ViewGroup;
import android.webkit.WebView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

@RunWith(AndroidJUnit4.class)
public class OfflinePlayTest {
    private Instrumentation getInstrumentation() { return InstrumentationRegistry.getInstrumentation(); }
    private WebView web;

    private void fixture(String script) throws Exception {
        js("isPaused=true");
        await("!isSendingAction");
        com.chaquo.python.PyObject module = com.chaquo.python.Python.getInstance().getModule("offline_engine");
        com.chaquo.python.PyObject globals = module.callAttr("__getattribute__", "__dict__");
        String setup = "from gui_server import WebMahjongSession\nfrom m1_tile import Hand, Tile\n"
            + "def h(codes): return Hand([Tile.from_str(c) for c in codes.split()])\n"
            + "def t(code): return Tile.from_str(code)\n"
            + "_session=WebMahjongSession()\ns=_session\np=s.game.players[0]\n" + script;
        com.chaquo.python.Python.getInstance().getModule("builtins").callAttr("exec", setup, globals);
        js("gameState=null; declareRiichiNext=false; fetchState()");
        await("gameState!==null && !isSendingAction");
        js("isPaused=false; startModal.style.display='none'; gameContainer.style.visibility='visible'; render(); checkAiTurn()");
    }

    @Test public void testChiPonKanAndReducedMotionOnDevice() throws Exception {
        launchGame();
        for (String kind : new String[]{"chi", "pon", "kan"}) {
            String target = kind.equals("chi") ? "3m" : "5z";
            String hand = kind.equals("chi") ? "1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s"
                : kind.equals("pon") ? "5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p"
                : "5z 5z 5z 1m 2m 4m 5m 7m 8m 1p 3p 5p 7p";
            fixture("p.hand=h('" + hand + "')\ns.game.current_turn=1\ns.current_drawn_tile=None\n"
                + "target=t('" + target + "')\ns.game.last_discard=target\ns.game.last_discard_player=1\n"
                + "s.game.players[1].discard_record.add(target)\n"
                + "s.pending_reaction={'player_idx':0,'target_tile':target,'actions':s.game.get_reaction_actions(0,target)}\n");
            assertEquals("true", js("gameState.pending_reaction.actions.some(a=>a.type==='" + kind + "')"));
            String wall = js("gameState.wall_remaining");
            js("document.querySelectorAll('#reaction-buttons button')[gameState.pending_reaction.actions.findIndex(a=>a.type==='" + kind + "')].click()");
            await("gameState.players[0].melds.length===1 && !isSendingAction");
            assertEquals("11", js("gameState.players[0].concealed_tiles.length"));
            assertEquals("true", js("document.getElementById('btn-riichi').disabled"));
            if (!kind.equals("kan")) {
                assertEquals(wall, js("gameState.wall_remaining"));
                assertEquals("true", js("gameState.must_discard_after_call && gameState.current_drawn_tile===null"));
            } else {
                assertEquals("true", js("gameState.current_drawn_tile!==null && !gameState.must_discard_after_call"));
            }
            js("reduceMotionToggle.checked=true; reduceMotionToggle.dispatchEvent(new Event('change'))");
            assertEquals("true", js("document.getElementById('btn-riichi').disabled"));
            assertEquals("\"none\"", js("getComputedStyle(document.querySelector('#human-melds .meld-group'),'::before').animationName"));
            int before = Integer.parseInt(js("gameState.players[0].discards.length"));
            js("document.querySelector('#human-hand-tiles .tile').click()");
            await("gameState.players[0].discards.length===" + (before + 1));
            js("isPaused=true");
            Thread.sleep(700);
        }
    }

    @Test public void testRiichiDiscardThenTsumoAndRonOnDevice() throws Exception {
        launchGame();
        fixture("p.hand=h('1m 2m 3m 1p 2p 3p 5p 6p 7p 9p 9p 8s 9s 4s')\n"
            + "s.current_drawn_tile=p.hand.concealed_tiles[-1]\np.last_drawn_tile=s.current_drawn_tile\n"
            + "s.game.players[1].hand=h('1m 2m 4m 5m 7m 8m 1p 3p 5p 7p 9p 1s 3s')\n"
            + "s.game.wall.tiles[:0]=[t(c) for c in '7z 4s 7z 7s'.split()]\n");
        assertEquals("true", js("gameState.human_turn_actions.can_riichi"));
        js("document.getElementById('btn-riichi').click()");
        assertEquals("true", js("document.querySelector('.tile-code-4s').classList.contains('riichi-candidate')"));
        js("document.querySelector('.tile-code-4s.riichi-candidate').click()");
        await("gameState.players[0].is_riichi && gameState.current_turn===0 && gameState.current_drawn_tile!==null");
        assertEquals("\"4s\"", js("gameState.current_drawn_tile.code"));
        assertEquals("false", js("gameState.human_turn_actions.can_tsumo"));
        int discards = Integer.parseInt(js("gameState.players[0].discards.length"));
        js("document.querySelector('#human-hand-tiles .tile').click()");
        assertEquals(String.valueOf(discards), js("gameState.players[0].discards.length"));
        js("document.getElementById('btn-tsumogiri').click()");
        await("gameState.current_turn===0 && gameState.human_turn_actions.can_tsumo===true");
        js("document.getElementById('btn-tsumo').click()");
        await("gameState.is_game_over && document.getElementById('gameover-modal').style.display==='flex'");
        assertEquals("\"tsumo\"", js("gameState.winning_type"));
        assertEquals("true", js("document.getElementById('gameover-title').textContent.includes('승리')"));

        fixture("p.hand=h('1m 2m 3m 4m 5m 6m 1p 2p 3p 7s 8s 9s 5z')\n"
            + "p.riichi_state.is_riichi=True\ns.game.current_turn=1\ns.current_drawn_tile=None\n"
            + "s.game.last_discard=t('5z')\ns.game.last_discard_player=1\ns.game.players[1].discard_record.add(t('5z'))\n"
            + "s.pending_reaction={'player_idx':0,'target_tile':t('5z'),'actions':s.game.get_reaction_actions(0,t('5z'))}\n");
        js("[...document.querySelectorAll('#reaction-buttons button')].find(b=>b.textContent.includes('론')).click()");
        await("gameState.is_game_over");
        assertEquals("\"ron\"", js("gameState.winning_type"));

        fixture("p.hand=h('1m 2m 3m 4m 5m 6m 1p 2p 3p 7s 8s 9s 5z 5z')\n"
            + "s.current_drawn_tile=p.hand.concealed_tiles[-1]\np.last_drawn_tile=s.current_drawn_tile\np.discard_record.add(t('5z'))\n");
        assertEquals("true", js("gameState.is_human_furiten && gameState.human_turn_actions.can_tsumo"));
        js("document.getElementById('btn-tsumo').click()");
        await("gameState.is_game_over && gameState.winning_type==='tsumo'");
    }

    @Test public void testThreeDifficultiesCompleteRoundsOnDevice() throws Exception {
        launchGame();
        for (String difficulty : new String[]{"low", "medium", "high"}) {
            fixture("s.difficulty='" + difficulty + "'\n");
            long limit = System.currentTimeMillis() + 150000;
            int lastRevision = -1;
            long lastProgress = System.currentTimeMillis();
            while (System.currentTimeMillis() < limit && !"true".equals(js("gameState.is_game_over"))) {
                int revision = Integer.parseInt(js("gameState.revision"));
                if (revision != lastRevision) { lastRevision = revision; lastProgress = System.currentTimeMillis(); }
                assertTrue("No stuck turn at " + difficulty + " revision " + revision, System.currentTimeMillis() - lastProgress < 15000);
                js("(()=>{if(isSendingAction||isPaused||gameState.is_game_over)return;"
                    + "if(gameState.pending_reaction && gameState.pending_reaction.player_idx===0){const bs=[...document.querySelectorAll('#reaction-buttons button')];"
                    + "const reaction=bs.find(b=>b.textContent.includes('론'))||bs.find(b=>b.textContent.includes('패스'));if(reaction)reaction.click();return;}"
                    + "if(gameState.current_turn!==0)return;"
                    + "if(gameState.human_turn_actions.can_tsumo){btnTsumo.click();return;}"
                    + "if(gameState.players[0].is_riichi){btnTsumogiri.click();return;}"
                    + "const tile=document.querySelector('#drawn-tile-slot .tile:not(.locked), #human-hand-tiles .tile:not(.locked)');if(tile)tile.click();})()");
                Thread.sleep(130);
            }
            assertEquals("Round finished: " + difficulty, "true", js("gameState.is_game_over"));
            assertEquals("true", js("['ron','tsumo','draw'].includes(gameState.winning_type)"));
            assertEquals("\"flex\"", js("document.getElementById('gameover-modal').style.display"));
            android.util.Log.i("MahjongPlaytest", difficulty + " finished: " + js("JSON.stringify({type:gameState.winning_type,winner:gameState.winner,revision:gameState.revision})"));
            js("document.getElementById('btn-modal-restart').click()");
            await("gameState.wall_remaining===95 && document.getElementById('start-modal').style.display==='flex'");
        }
        assertEquals("true", js("JSON.parse(localStorage.getItem(RECORD_STORAGE_KEY)).records.length>=3"));
    }

    private String js(String code) throws Exception {
        AtomicReference<String> result = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1);
        getInstrumentation().runOnMainSync(() -> web.evaluateJavascript(code, value -> {
            result.set(value); done.countDown();
        }));
        assertTrue("JavaScript callback", done.await(10, TimeUnit.SECONDS));
        return result.get();
    }

    private void await(String condition) throws Exception {
        long deadline = System.currentTimeMillis() + 20000;
        while (System.currentTimeMillis() < deadline) {
            if ("true".equals(js(condition))) return;
            Thread.sleep(100);
        }
        fail("Timed out: " + condition + "; page: " + js("document.body.innerText"));
    }

    private MainActivity launchGame() throws Exception {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        MainActivity activity = (MainActivity) getInstrumentation().startActivitySync(intent);
        long deadline = System.currentTimeMillis() + 30000;
        while (web == null && System.currentTimeMillis() < deadline) {
            getInstrumentation().runOnMainSync(() -> {
                ViewGroup content = activity.findViewById(android.R.id.content);
                if (content.getChildAt(0) instanceof WebView) web = (WebView) content.getChildAt(0);
            });
            Thread.sleep(100);
        }
        assertNotNull("Offline WebView started", web);
        await("typeof gameState !== 'undefined' && gameState !== null");
        return activity;
    }

    @Test public void testOfflineStartDiscardPauseRestartAndStorage() throws Exception {
        MainActivity activity = launchGame();
        long deadline;
        assertEquals("No internet permission", android.content.pm.PackageManager.PERMISSION_DENIED,
            activity.checkSelfPermission("android.permission.INTERNET"));
        assertEquals("14", js("gameState.players[0].concealed_tiles.length"));
        assertEquals("95", js("gameState.wall_remaining"));
        assertEquals("true", js("(()=>{const b=document.getElementById('btn-start-game').getBoundingClientRect();return b.top>=0 && b.bottom<=innerHeight})()"));
        js("document.getElementById('btn-start-game').click()");
        await("document.getElementById('start-modal').style.display === 'none'");
        assertEquals("14", js("document.querySelectorAll('#human-hand-tiles .tile, #drawn-tile-slot .tile').length"));
        js("document.getElementById('btn-pause').click()");
        await("document.getElementById('pause-modal').style.display === 'flex'");
        js("document.getElementById('btn-resume').click()");
        await("document.getElementById('pause-modal').style.display === 'none'");
        js("document.querySelector('#human-hand-tiles .tile').click()");
        await("gameState.players[0].discards.length === 1");
        await("gameState.current_turn === 0 || gameState.is_game_over || gameState.pending_reaction !== null");
        js("localStorage.setItem('offline-test','preserved')");
        getInstrumentation().runOnMainSync(() -> web.evaluateJavascript("document.getElementById('btn-restart').click()", null));
        boolean confirmed = false;
        deadline = System.currentTimeMillis() + 10000;
        while (!confirmed && System.currentTimeMillis() < deadline) {
            android.view.accessibility.AccessibilityNodeInfo root = getInstrumentation().getUiAutomation().getRootInActiveWindow();
            if (root != null) {
                for (android.view.accessibility.AccessibilityNodeInfo button : root.findAccessibilityNodeInfosByText("새 게임 시작")) {
                    confirmed = button.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK);
                    if (confirmed) break;
                }
            }
            Thread.sleep(100);
        }
        assertTrue("New-game confirmation shown", confirmed);
        await("document.getElementById('start-modal').style.display === 'flex' && gameState.wall_remaining === 95");
        assertEquals("\"preserved\"", js("localStorage.getItem('offline-test')"));
        assertEquals("0", js("gameState.players[0].discards.length"));
        assertEquals("true", js("gameState.can_change_difficulty"));
        js("window.beforeOfflineReload = true");
        getInstrumentation().runOnMainSync(() -> web.reload());
        await("typeof window.beforeOfflineReload === 'undefined' && typeof gameState !== 'undefined' && gameState !== null && document.readyState === 'complete'");
        assertEquals("\"preserved\"", js("localStorage.getItem('offline-test')"));
        js("document.getElementById('btn-start-game').click()");
        await("document.getElementById('start-modal').style.display === 'none'");
        assertEquals("true", js("(()=>{const t=document.querySelector('#human-hand-tiles .tile').getBoundingClientRect();return t.left>=0 && t.bottom<=innerHeight})()"));
        getInstrumentation().waitForIdleSync();
        Thread.sleep(300);
        android.graphics.Bitmap screenshot = getInstrumentation().getUiAutomation().takeScreenshot();
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(new java.io.File(activity.getFilesDir(), "offline-play.png"))) {
            screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, out);
        }
    }
}
