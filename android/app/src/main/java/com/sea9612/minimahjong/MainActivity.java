package com.sea9612.minimahjong;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.JsResult;
import android.widget.TextView;
import androidx.webkit.WebViewAssetLoader;
import com.chaquo.python.Python;
import com.chaquo.python.PyObject;
import com.chaquo.python.android.AndroidPlatform;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;

public class MainActivity extends Activity {
    private WebView web;
    private static final String ORIGIN = "appassets.androidplatform.net";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        immersive();
        TextView loading = new TextView(this);
        loading.setText("미니마작을 준비하고 있습니다…\n인터넷 연결 없이 실행됩니다.");
        loading.setTextSize(20);
        loading.setGravity(android.view.Gravity.CENTER);
        setContentView(loading);
        new Thread(() -> {
            try {
                File engine = new File(getFilesDir(), "engine");
                copyAssets("engine", engine);
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                PyObject module = Python.getInstance().getModule("offline_engine");
                module.callAttr("initialize", engine.getAbsolutePath());
                runOnUiThread(() -> { if (!isDestroyed()) openGame(module); });
            } catch (Exception error) {
                android.util.Log.e("MiniMahjong", "Offline startup failed", error);
                runOnUiThread(() -> loading.setText("게임을 시작하지 못했습니다.\n앱을 종료한 뒤 다시 실행해 주세요."));
            }
        }, "mahjong-startup").start();
    }

    private void copyAssets(String path, File target) throws Exception {
        String[] children = getAssets().list(path);
        if (children != null && children.length > 0) {
            if (!target.isDirectory() && !target.mkdirs()) throw new java.io.IOException("Cannot create engine directory");
            for (String child : children) copyAssets(path + "/" + child, new File(target, child));
        } else {
            try (InputStream in = getAssets().open(path); FileOutputStream out = new FileOutputStream(target)) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
            }
        }
    }

    private void openGame(PyObject module) {
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportZoom(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        final WebViewAssetLoader assets = new WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if ("https".equals(request.getUrl().getScheme()) && ORIGIN.equals(request.getUrl().getHost())) {
                    WebResourceResponse response = assets.shouldInterceptRequest(request.getUrl());
                    if (response != null) return response;
                }
                return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                    java.util.Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !ORIGIN.equals(request.getUrl().getHost());
            }
        });
        web.addJavascriptInterface(new GameBridge(module), "AndroidGame");
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsConfirm(WebView view, String url, String message, JsResult result) {
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("새 게임 시작", (dialog, which) -> result.confirm())
                    .setNegativeButton("취소", (dialog, which) -> result.cancel())
                    .setOnCancelListener(dialog -> result.cancel()).show();
                return true;
            }
        });
        setContentView(web);
        web.loadUrl("https://" + ORIGIN + "/assets/game/index.html");
    }

    public static class GameBridge {
        private final PyObject engine;
        GameBridge(PyObject engine) { this.engine = engine; }
        @JavascriptInterface public String request(String body) {
            try { return engine.callAttr("request", body).toString(); }
            catch (Exception error) {
                android.util.Log.e("MiniMahjong", "Game request failed", error);
                return "{\"status\":500,\"data\":{\"error\":\"기기 내부 게임 처리 오류\"}}";
            }
        }
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }
    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) immersive();
    }
    @Override protected void onPause() {
        if (web != null) {
            web.evaluateJavascript("window.pauseOfflineGame && window.pauseOfflineGame()", null);
            web.onPause();
        }
        super.onPause();
    }
    @Override protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }
    @Override public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript("window.pauseOfflineGame && window.pauseOfflineGame()", null);
        new AlertDialog.Builder(this).setMessage("게임을 종료할까요? 현재 대국은 앱을 완전히 종료하면 초기화됩니다.")
            .setPositiveButton("종료", (dialog, which) -> finish())
            .setNegativeButton("계속하기", null).show();
    }
    @Override protected void onDestroy() {
        if (web != null) { web.removeJavascriptInterface("AndroidGame"); web.destroy(); web = null; }
        super.onDestroy();
    }
}
