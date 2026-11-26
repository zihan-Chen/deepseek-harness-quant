/* ui_v2/components/search.js — ★2026-08-13 #311 单股搜索/全息（恢复 stock_check 个股交叉评级）
   用法：LW.search.render('search-box')  渲染搜索框；输入代码/名称 → /api/stock_check → 全息模态框
   全息内容：综合评级 + 结论 + 池状态 + 信号族 + 四维 + 止损 + 持仓 + 远期 */
(function () {
  'use strict';
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]); }); };
  function pv(v, d) { return (v != null && !isNaN(v)) ? (v * 100).toFixed(d || 0) + '%' : '—'; }
  function f(v, d) { return (v == null || v === '' || (typeof v === 'number' && isNaN(v))) ? (d || '—') : v; }

  function close() {
    var o = document.getElementById('lw-search-ov');
    if (o) o.remove();
  }

  function modal(d) {
    close();
    var r = d.rating || {};
    var ps = d.pool_status || {};
    var sg = d.signal || {};
    var sp = d.stop_plan || {};
    var pos = d.position || {};
    var fwd = d.forward || {};
    var dims = d.dimensions || {};
    // ★2026-11-26：NA（证据不足/新股样本不足）单独用灰色，不能跟着 E 一起标红——
    //   否则"数据不够"看起来像"看空"（用户反馈：短线池推荐的次新股被诊断成 E 回避）。
    var gradeCls = r.grade === 'A' ? '#27ae60' : r.grade === 'B' ? '#5e6ad2'
                 : r.grade === 'C' ? '#f2c94c'
                 : (r.grade === 'NA' ? '#94A3B8' : '#eb5757');
    // 池状态徽章
    var poolBadges = [
      ps.in_opp_pool ? '<span class="pv-badge pv-ot-value">机会池</span>' : '',
      ps.in_pitch ? '<span class="pv-badge pv-ot-quality_gap">Pitch 长线</span>' : '',
      ps.in_tech_pitch ? '<span class="pv-badge pv-ot-tech_sentiment">短线</span>' : '',
      ps.in_forward_track ? '<span class="pv-badge pv-ot-pv_consensus">远期池</span>' : ''
    ].join('');
    // ★2026-11-26 修复：四维评分读错了字段。
    //   维度对象 `dimensions.tech / valuation` 里根本没有 score 字段（只有 state/mode 等描述），
    //   `dimensions.opportunity.score` 在未命中时是 null → 四个条全是 0 分（用户反馈"四维评分都没有"）。
    //   真实分数在 `d.dim_scores`（opportunity/risk/tech/valuation），这里改用它，并补上中文名、
    //   满分分母与维度要点，负分（风控/技术可为负）单独标红。
    var DIM_META = {
      opportunity: { cn: '机会', max: 40 },
      risk: { cn: '风控', max: 30 },
      tech: { cn: '技术', max: 15 },
      valuation: { cn: '估值', max: 15 }
    };
    var dimScores = d.dim_scores || {};
    function dimNote(k, v) {
      v = v || {};
      if (k === 'opportunity') {
        return v.otype_cn ? ('命中「' + v.otype_cn + '」' + (v.rank_in_type ? ' 同类#' + v.rank_in_type : '')) : '未命中机会类';
      }
      if (k === 'risk') {
        var lv = v.level || '—';
        var nf = (v.flags || []).length;
        return '风控 ' + lv + (nf ? ('（' + nf + ' 项红旗）') : '');
      }
      if (k === 'tech') {
        return v.state ? String(v.state) : '样本不足（<60 个交易日）';
      }
      if (k === 'valuation') {
        var bits = [v.mode || '—'];
        if (v.roe != null) bits.push('ROE ' + v.roe + '%');
        if (v.pe != null) bits.push('PE ' + v.pe);
        if (v.pb != null) bits.push('PB ' + v.pb);
        return bits.join(' · ');
      }
      return '';
    }
    var dimHtml = Object.keys(DIM_META).map(function (k) {
      var meta = DIM_META[k];
      var raw = dimScores[k];
      var s = (raw != null && !isNaN(raw)) ? +raw : 0;
      var pct = Math.max(0, Math.min(100, (s / meta.max) * 100));
      var neg = s < 0;
      var color = neg ? '#eb5757' : (s / meta.max >= 0.6 ? '#27ae60' : (s / meta.max >= 0.3 ? '#f2c94c' : '#94A3B8'));
      return '<div class="dim-row" title="' + esc(dimNote(k, dims[k])) + '">' +
        '<div class="dim-top"><b>' + meta.cn + '</b>' +
        '<span style="color:' + color + '">' + s + ' / ' + meta.max + '</span></div>' +
        '<div class="dim-bar"><div class="dim-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
        '<div class="mini" style="margin-top:2px;color:#94A3B8;font-size:11px">' + esc(dimNote(k, dims[k])) + '</div></div>';
    }).join('');
    var ov = document.createElement('div');
    ov.id = 'lw-search-ov';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto';
    ov.innerHTML =
      '<div style="background:#131316;border-radius:14px;max-width:720px;width:100%;padding:22px 24px;box-shadow:0 20px 60px -12px rgba(0,0,0,.4)">' +
        '<div style="display:flex;align-items:baseline;gap:10px">' +
          '<b style="font-size:18px;color:#f4f4f5">' + esc(d.code) + ' ' + esc(d.name) + '</b>' +
          '<span style="font-size:12px;color:#a1a1aa">' + esc(d.industry || '') + ' · ' + esc(d.date || '') + '</span>' +
          '<button onclick="document.getElementById(\'lw-search-ov\').remove()" style="margin-left:auto;border:none;background:none;font-size:20px;cursor:pointer;color:#a1a1aa">×</button></div>' +
        '<div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
          '<span class="pv-badge" style="font-weight:700;color:#ffffff;background:' + gradeCls + '">评级 ' + esc(r.grade) + ' · ' + f(r.label) + ' ' + f(r.score) + ' 分</span>' +
          poolBadges + '</div>' +
        (d.conclusion ? '<div class="pv-origin" style="margin-top:10px"><div class="pv-origin-t">综合结论</div>' + esc(d.conclusion) + '</div>' : '') +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px">' +
          '<div class="v2-card" style="margin-top:0;padding:14px"><h2 style="font-size:13px">信号</h2>' +
            '<div class="mini">家族 <b>' + esc(sg.signal_family || '—') + '</b> · 信号分 <b>' + f(sg.signal_score != null ? (+sg.signal_score).toFixed(0) : null) + '</b></div>' +
            '<div class="mini" style="margin-top:4px">无效因子 ' + f(sg.n_invalid, 0) + ' · 有效 ' + f(sg.factor_eff_n, 0) + '</div></div>' +
          '<div class="v2-card" style="margin-top:0;padding:14px"><h2 style="font-size:13px">止损计划</h2>' +
            '<div class="mini">硬止损 ' + pv(sp.stop_loss_pct) + ' · 时间止损 ' + f(sp.time_stop_weeks) + ' 周</div>' +
            '<div class="mini" style="margin-top:4px">最大回撤 ' + pv(sp.max_drawdown_pct) + ' · 移动 MA' + f(sp.trailing_ma) + '</div></div>' +
        '</div>' +
        '<div class="v2-card" style="margin-top:12px;padding:14px"><h2 style="font-size:13px">四维评分</h2>' + (dimHtml || '<div class="mini">—</div>') +
          (d.coverage && (d.coverage.missing || []).length
            ? '<div class="mini" style="margin-top:8px;color:#f2c94c;font-size:11px">数据缺口：' +
              esc((d.coverage.missing || []).join(' / ')) + (d.coverage.new_listing ? '（新股：上市 ' + esc(d.coverage.bars_days) + ' 个交易日）' : '') +
              ' —— 缺数据的维度按 0 分参与合计，不等同于负面评价</div>'
            : '') +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px">' +
          '<div class="v2-card" style="margin-top:0;padding:14px"><h2 style="font-size:13px">持仓</h2>' +
            '<div class="mini">' + esc(f(pos.status, '未持仓')) + (pos.entry_date ? ' · ' + esc(pos.entry_date) : '') + '</div>' +
            (pos.entry_price != null ? '<div class="mini" style="margin-top:4px">入池价 ' + esc(pos.entry_price) + (pos.stop != null ? ' · 止损 ' + esc(pos.stop) : '') + (pos.target != null ? ' · 止盈 ' + esc(pos.target) : '') + '</div>' : '') + '</div>' +
          '<div class="v2-card" style="margin-top:0;padding:14px"><h2 style="font-size:13px">远期验证</h2>' +
            '<div class="mini">' + esc(f(fwd.entry_date, '未入远期池')) + (fwd.decided ? ' · 已审批' : '') + '</div>' +
            (fwd.rets ? '<div class="mini" style="margin-top:4px">' + Object.keys(fwd.rets).map(function (k) { var v = fwd.rets[k]; return k + ' ' + (v != null ? (v > 0 ? '+' : '') + (v * 100).toFixed(2) + '%' : '—'); }).join(' · ') + '</div>' : '') + '</div>' +
        '</div>' +
      '</div>';
    ov.onclick = function (e) { if (e.target === ov) close(); };
    document.body.appendChild(ov);
  }

  function search(q) {
    if (!q) return;
    var btn = document.getElementById('srch-btn');
    if (btn) { btn.disabled = true; btn.textContent = '查询中…'; }
    fetch('/api/stock_check?code=' + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
      if (btn) { btn.disabled = false; btn.textContent = '搜索'; }
      if (d && d.ok) { modal(d); }
      else { alert((d && d.error) || '未找到该股票'); }
    }).catch(function (e) {
      if (btn) { btn.disabled = false; btn.textContent = '搜索'; }
      alert('查询失败：' + e.message);
    });
  }

  window.LW = window.LW || {};
  window.LW.search = {
    render: function (elId, placeholder) {
      var el = document.getElementById(elId);
      if (!el) return;
      el.innerHTML =
        '<div style="display:flex;gap:6px;align-items:center">' +
        '<input id="srch-in" placeholder="' + esc(placeholder || '代码/名称搜索 · 如 000567 或 海德') + '" ' +
        'style="flex:1;padding:6px 10px;border:1px solid #2a2a30;border-radius:8px;font-size:13px;outline:none;color:#f4f4f5;background:#131316">' +
        '<button id="srch-btn" class="v2-btn" style="padding:6px 12px">搜索</button></div>';
      var inp = document.getElementById('srch-in');
      var btn = document.getElementById('srch-btn');
      btn.onclick = function () { search(inp.value.trim()); };
      inp.onkeydown = function (e) { if (e.key === 'Enter') search(inp.value.trim()); };
    }
  };
})();
