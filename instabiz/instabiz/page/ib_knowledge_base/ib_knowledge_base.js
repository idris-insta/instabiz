frappe.pages["ib-knowledge-base"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Knowledge Base",
		single_column: true,
	});

	page.set_secondary_action("Download PDF", () => {
		window.open("/files/instabiz_knowledge_base.pdf", "_blank");
	}, "download");

	$(wrapper).find(".layout-main-section").html(_kb_html());

	if (!document.getElementById("ib-kb-drawer")) {
		document.body.insertAdjacentHTML("beforeend", _kb_drawer_html());
	}

	frappe.call({
		method: "instabiz.instabiz.page.ib_knowledge_base.ib_knowledge_base.get_kb_data",
		callback(r) {
			_setup_kb(wrapper, new Set(((r.message || {}).roles) || []));
		},
		error() {
			_setup_kb(wrapper, new Set(frappe.boot.user.roles || []));
		},
	});
};

// ── HTML shells ──────────────────────────────────────────────────────────────

function _kb_html() {
	return `
<style>
:root {
	--kb-primary: #d97757;
	--kb-primary-dark: #b85c3a;
	--kb-radius: 10px;
	--kb-transition: 200ms ease;
}

.ib-kb { font-family: var(--font-stack); color: var(--text-color); padding-bottom: 60px; }

/* Hero */
.ib-kb-hero {
	background: linear-gradient(135deg, #d97757 0%, #b85c3a 60%, #9a4a2e 100%);
	color: #fff;
	border-radius: 14px;
	padding: 28px 32px;
	margin-bottom: 22px;
	display: flex;
	align-items: center;
	gap: 20px;
}
.ib-kb-hero-icon {
	width: 52px;
	height: 52px;
	border-radius: 12px;
	background: rgba(255,255,255,.18);
	border: 1.5px solid rgba(255,255,255,.35);
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	color: #fff;
}
.ib-kb-hero h1 { font-size: 22px; font-weight: 700; margin: 0 0 6px; letter-spacing: -0.3px; }
.ib-kb-hero-meta { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
.ib-kb-hero-stat {
	background: rgba(255,255,255,.18);
	border: 1px solid rgba(255,255,255,.3);
	border-radius: 20px;
	padding: 3px 12px;
	font-size: 11.5px;
	font-weight: 600;
}
.ib-kb-hero-actions { margin-left: auto; flex-shrink: 0; }
.ib-kb-hero-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	background: rgba(255,255,255,.2);
	border: 1.5px solid rgba(255,255,255,.5);
	color: #fff;
	padding: 8px 18px;
	border-radius: 8px;
	font-size: 13px;
	font-weight: 600;
	cursor: pointer;
	text-decoration: none;
	transition: background var(--kb-transition);
}
.ib-kb-hero-btn:hover { background: rgba(255,255,255,.35); color: #fff; }

/* Search */
.ib-kb-search-wrap {
	position: relative;
	margin-bottom: 16px;
}
.ib-kb-search {
	width: 100%;
	padding: 13px 70px 13px 46px;
	border: 2px solid var(--border-color);
	border-radius: 12px;
	font-size: 14px;
	background: var(--card-bg);
	color: var(--text-color);
	outline: none;
	transition: border-color var(--kb-transition), box-shadow var(--kb-transition);
}
.ib-kb-search:focus {
	border-color: var(--kb-primary);
	box-shadow: 0 0 0 3px rgba(217,119,87,.12);
}
.ib-kb-search-icon {
	position: absolute;
	left: 14px;
	top: 50%;
	transform: translateY(-50%);
	color: var(--text-muted);
	display: flex;
	pointer-events: none;
}
.ib-kb-search-kbd {
	position: absolute;
	right: 14px;
	top: 50%;
	transform: translateY(-50%);
	font-size: 10px;
	font-weight: 700;
	color: var(--text-muted);
	background: var(--bg-color);
	border: 1px solid var(--border-color);
	border-radius: 5px;
	padding: 3px 7px;
	letter-spacing: .5px;
	pointer-events: none;
	transition: opacity var(--kb-transition);
}
.ib-kb-search:focus ~ .ib-kb-search-kbd { opacity: 0; }

/* Suggestions dropdown */
.ib-kb-suggestions {
	position: absolute;
	top: calc(100% + 1px);
	left: 0; right: 0;
	background: var(--card-bg);
	border: 2px solid var(--kb-primary);
	border-top: none;
	border-radius: 0 0 12px 12px;
	box-shadow: 0 10px 30px rgba(0,0,0,.12);
	z-index: 300;
	overflow: hidden;
	display: none;
	max-height: 380px;
	overflow-y: auto;
}
.ib-kb-suggestions.open { display: block; }
.ib-kb-sug-item {
	display: flex;
	align-items: center;
	gap: 12px;
	padding: 10px 16px;
	cursor: pointer;
	border-bottom: 1px solid var(--border-color);
	transition: background var(--kb-transition);
}
.ib-kb-sug-item:last-child { border-bottom: none; }
.ib-kb-sug-item:hover, .ib-kb-sug-item.kb-focused {
	background: var(--bg-color);
}
.ib-kb-sug-icon {
	width: 32px;
	height: 32px;
	border-radius: 8px;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
}
.ib-kb-sug-text { flex: 1; min-width: 0; }
.ib-kb-sug-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ib-kb-sug-desc { font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ib-kb-sug-section { font-size: 10px; color: var(--kb-primary); font-weight: 700; flex-shrink: 0; }
.ib-kb-sug-empty { padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px; }
.ib-kb-sug-footer {
	padding: 8px 16px;
	background: var(--bg-color);
	font-size: 11px;
	color: var(--text-muted);
	text-align: center;
	border-top: 1px solid var(--border-color);
}

/* Autocorrect hint */
.ib-kb-correction {
	margin-bottom: 12px;
	font-size: 13px;
	color: var(--text-muted);
}
.ib-kb-correction a { color: var(--kb-primary); cursor: pointer; font-weight: 600; text-decoration: underline; }

/* Category pills */
.ib-kb-cats {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	margin-bottom: 18px;
}
.ib-kb-cat {
	padding: 5px 14px;
	border-radius: 20px;
	border: 1.5px solid var(--border-color);
	background: var(--card-bg);
	font-size: 12px;
	font-weight: 600;
	cursor: pointer;
	color: var(--text-muted);
	transition: all var(--kb-transition);
	user-select: none;
}
.ib-kb-cat:hover { border-color: var(--kb-primary); color: var(--kb-primary); }
.ib-kb-cat.active {
	background: var(--kb-primary);
	border-color: var(--kb-primary);
	color: #fff;
}

/* Recently viewed */
.ib-kb-recent {
	display: flex;
	align-items: center;
	gap: 8px;
	flex-wrap: wrap;
	margin-bottom: 16px;
}
.ib-kb-recent-label {
	font-size: 11px;
	color: var(--text-muted);
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: .5px;
	white-space: nowrap;
}
.ib-kb-recent-chip {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	padding: 3px 11px 3px 8px;
	border-radius: 16px;
	border: 1px solid var(--border-color);
	font-size: 11.5px;
	color: var(--text-color);
	cursor: pointer;
	background: var(--card-bg);
	transition: all var(--kb-transition);
	text-decoration: none;
}
.ib-kb-recent-chip:hover {
	border-color: var(--kb-primary);
	color: var(--kb-primary);
}
.ib-kb-recent-chip .rci { display: flex; align-items: center; }

/* Quick links */
.ib-kb-quick-links {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
	gap: 10px;
	margin-bottom: 22px;
}
.ib-kb-quick-link {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 12px 14px;
	text-align: center;
	cursor: pointer;
	transition: all var(--kb-transition);
	text-decoration: none;
	display: block;
}
.ib-kb-quick-link:hover {
	border-color: var(--kb-primary);
	transform: translateY(-2px);
	box-shadow: 0 6px 16px rgba(217,119,87,.14);
}
.ib-kb-quick-link .icon { width: 36px; height: 36px; margin: 0 auto 8px; display: flex; align-items: center; justify-content: center; border-radius: 8px; background: var(--bg-color); }
.ib-kb-quick-link .label { font-size: 11.5px; font-weight: 600; color: var(--text-color); }

/* Workflow */
.ib-kb-workflow {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: var(--kb-radius);
	padding: 18px 20px;
	margin-bottom: 20px;
}
.ib-kb-workflow h3 {
	font-size: 13px;
	font-weight: 700;
	margin: 0 0 14px;
	color: var(--text-color);
	display: flex;
	align-items: center;
	gap: 8px;
}
.ib-kb-flow { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.ib-kb-flow-step {
	background: var(--bg-color);
	border: 1.5px solid var(--border-color);
	padding: 7px 14px;
	border-radius: 8px;
	font-size: 12px;
	font-weight: 600;
	cursor: pointer;
	transition: all var(--kb-transition);
	position: relative;
}
.ib-kb-flow-step:hover {
	background: var(--kb-primary);
	color: #fff;
	border-color: var(--kb-primary);
	transform: translateY(-1px);
	box-shadow: 0 4px 10px rgba(217,119,87,.25);
}
.ib-kb-flow-step.active {
	background: var(--kb-primary-dark);
	color: #fff;
	border-color: var(--kb-primary-dark);
}
.ib-kb-flow-arrow { color: var(--kb-primary); font-size: 16px; font-weight: 700; }

/* Workflow detail */
.ib-kb-wf-detail {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: var(--kb-radius);
	overflow: hidden;
	margin-top: 14px;
	display: none;
}
.ib-kb-wf-detail.open { display: block; }
.ib-kb-wf-detail-hdr {
	background: var(--kb-primary);
	color: #fff;
	padding: 12px 18px;
	display: flex;
	align-items: center;
	justify-content: space-between;
}
.ib-kb-wf-detail-hdr h4 { margin: 0; font-size: 14px; font-weight: 600; }
.ib-kb-wf-close { cursor: pointer; font-size: 18px; opacity: .8; line-height: 1; }
.ib-kb-wf-close:hover { opacity: 1; }
.ib-kb-wf-body { padding: 18px; }

/* Slim top bar */
.ib-kb-slimbar {
	display: flex;
	align-items: center;
	gap: 12px;
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 9px 14px;
	margin-bottom: 10px;
}
.ib-kb-slimbar-icon { color: var(--kb-primary); display: flex; flex-shrink: 0; }
.ib-kb-slimbar-title { font-weight: 700; font-size: 14px; white-space: nowrap; }
.ib-kb-slimbar-stat { font-size: 11px; color: var(--text-muted); white-space: nowrap; flex-shrink: 0; }
.ib-kb-slimbar-search { flex: 1; min-width: 140px; position: relative; margin-bottom: 0 !important; }
.ib-kb-slimbar-search .ib-kb-search {
	padding: 7px 60px 7px 34px;
	border-width: 1.5px;
	border-radius: 8px;
	font-size: 12.5px;
}
.ib-kb-slimbar-search .ib-kb-search-icon { left: 11px; }
.ib-kb-slimbar-search .ib-kb-search-icon iconify-icon { width: 14px; height: 14px; }
.ib-kb-slimbar-search .ib-kb-search-kbd { right: 10px; padding: 2px 6px; font-size: 9px; }
.ib-kb-slimbar-more {
	display: flex; align-items: center; gap: 4px;
	background: var(--bg-color); border: 1px solid var(--border-color);
	border-radius: 8px; padding: 7px 12px; font-size: 12px; font-weight: 600;
	color: var(--text-muted); cursor: pointer; white-space: nowrap; flex-shrink: 0;
	transition: all var(--kb-transition);
}
.ib-kb-slimbar-more:hover { color: var(--kb-primary); border-color: var(--kb-primary); }
.ib-kb-slimbar-more .chev { transition: transform .2s ease; display: inline-flex; }
.ib-kb-slimbar-more.open .chev { transform: rotate(180deg); }
.ib-kb-slimbar-pdf {
	display: flex; align-items: center; gap: 5px; flex-shrink: 0;
	background: var(--kb-primary); color: #fff; border-radius: 8px;
	padding: 7px 12px; font-size: 12px; font-weight: 600; text-decoration: none;
	transition: background var(--kb-transition);
}
.ib-kb-slimbar-pdf:hover { background: var(--kb-primary-dark); color: #fff; }

.ib-kb-more-panel {
	max-height: 0;
	overflow: hidden;
	transition: max-height .3s ease;
}
.ib-kb-more-panel.open { max-height: 900px; margin-bottom: 14px; }

/* Tabs — same pill language as .ib-kb-cat for visual consistency */
.ib-kb-tabbar {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	margin-bottom: 14px;
}
.ib-kb-tab {
	display: flex;
	align-items: center;
	gap: 7px;
	padding: 6px 14px 6px 7px;
	border: 1.5px solid var(--border-color);
	border-radius: 20px;
	background: var(--card-bg);
	cursor: pointer;
	user-select: none;
	white-space: nowrap;
	transition: all var(--kb-transition);
	animation: kb-fadein .3s ease both;
}
.ib-kb-tab:hover { border-color: var(--kb-primary); }
.ib-kb-tab.active { background: var(--kb-primary); border-color: var(--kb-primary); }
.ib-kb-tab.active .ib-kb-tab-title { color: #fff; }
.ib-kb-tab.active .ib-kb-tab-count { background: rgba(255,255,255,.25); color: #fff; }
.ib-kb-tab.active .ib-kb-tab-icon { background: rgba(255,255,255,.25) !important; color: #fff !important; }
.ib-kb-tab-icon {
	width: 22px;
	height: 22px;
	border-radius: 50%;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
}
.ib-kb-tab-title { font-weight: 700; font-size: 12.5px; color: var(--text-color); }
.ib-kb-tab-count {
	font-size: 10px;
	color: var(--text-muted);
	background: var(--bg-color);
	padding: 1px 7px;
	border-radius: 9px;
	font-weight: 600;
}

/* Content pane */
.ib-kb-pane {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: var(--kb-radius);
	max-height: 62vh;
	overflow-y: auto;
	animation: kb-fadein .25s ease both;
}
.ib-kb-pane-search-group {
	padding: 10px 16px 4px;
	font-size: 10.5px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: .4px;
	color: var(--text-muted);
	background: var(--bg-color);
}
@keyframes kb-fadein {
	from { opacity: 0; transform: translateY(6px); }
	to   { opacity: 1; transform: translateY(0); }
}

/* Section items */
.ib-kb-item {
	display: flex;
	gap: 10px;
	padding: 10px 16px;
	cursor: pointer;
	border-bottom: 1px solid var(--border-color);
	transition: background var(--kb-transition);
}
.ib-kb-item:last-child { border-bottom: none; }
.ib-kb-item:hover { background: var(--bg-color); }
.ib-kb-item-num {
	font-size: 9.5px;
	color: var(--kb-primary);
	font-weight: 800;
	min-width: 22px;
	padding-top: 3px;
	letter-spacing: .5px;
}
.ib-kb-item-content { flex: 1; min-width: 0; }
.ib-kb-item-title { font-size: 13px; font-weight: 600; flex: 1; min-width: 0; }
.ib-kb-item-desc {
	font-size: 11.5px;
	color: var(--text-muted);
	line-height: 1.55;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
	overflow: hidden;
}
.ib-kb-item-footer {
	display: flex;
	align-items: center;
	gap: 10px;
	margin-top: 5px;
}
.ib-kb-item-link {
	font-size: 11px;
	color: var(--kb-primary);
	text-decoration: none;
	font-weight: 600;
	display: inline-flex;
	align-items: center;
	gap: 3px;
}
.ib-kb-item-link:hover { text-decoration: underline; color: var(--kb-primary-dark); }
.ib-kb-item-arrow {
	margin-left: auto;
	font-size: 11px;
	color: var(--text-muted);
	opacity: 0;
	transition: opacity var(--kb-transition);
}
.ib-kb-item:hover .ib-kb-item-arrow { opacity: 1; }

/* Last-updated badge under drawer title */
.ib-kb-updated {
	font-size: 10.5px;
	color: var(--text-muted);
	text-transform: uppercase;
	letter-spacing: 0.04em;
	font-weight: 600;
	margin: -6px 0 10px;
}

/* Note / Tip boxes */
.ib-kb-note {
	background: #fdf9f7;
	border-left: 3px solid var(--kb-primary);
	padding: 9px 13px;
	margin: 10px 0;
	font-size: 12px;
	border-radius: 0 6px 6px 0;
	line-height: 1.6;
}
.ib-kb-tip {
	background: #f0f9f0;
	border-left: 3px solid #1a7f37;
	padding: 9px 13px;
	margin: 10px 0;
	font-size: 12px;
	border-radius: 0 6px 6px 0;
	line-height: 1.6;
}

/* Steps list */
.ib-kb-steps {
	list-style: none;
	margin: 10px 0;
	padding: 0;
	counter-reset: kbstep;
}
.ib-kb-steps li {
	counter-increment: kbstep;
	padding: 7px 0 7px 36px;
	position: relative;
	font-size: 13px;
	border-bottom: 1px solid var(--border-color);
	line-height: 1.55;
}
.ib-kb-steps li:last-child { border-bottom: none; }
.ib-kb-steps li::before {
	content: counter(kbstep);
	position: absolute;
	left: 0;
	top: 6px;
	background: var(--kb-primary);
	color: #fff;
	width: 22px;
	height: 22px;
	border-radius: 50%;
	text-align: center;
	font-size: 10px;
	line-height: 22px;
	font-weight: 700;
}

/* Inline doctype links */
.ib-kb-doclink {
	color: var(--kb-primary);
	font-weight: 600;
	text-decoration: none;
	border-bottom: 1px dotted rgba(217,119,87,.4);
}
.ib-kb-doclink:hover { text-decoration: underline; color: var(--kb-primary-dark); }

/* No results */
.ib-kb-no-results {
	text-align: center;
	padding: 50px 20px;
	color: var(--text-muted);
}
.ib-kb-no-results .nr-icon { width: 52px; height: 52px; margin: 0 auto 12px; display: flex; align-items: center; justify-content: center; background: var(--bg-color); border-radius: 50%; color: var(--text-muted); }
.ib-kb-no-results p { font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.ib-kb-no-results small { font-size: 12px; }
.ib-kb-no-results button {
	background: none;
	border: none;
	color: var(--kb-primary);
	cursor: pointer;
	font-size: 12px;
	font-weight: 600;
	text-decoration: underline;
	padding: 0;
}

/* Search highlights */
mark.ib-hl { background: #ffe082; color: inherit; padding: 0 1px; border-radius: 2px; }

/* Item title row with badges */
.ib-kb-item-title-row { display: flex; align-items: flex-start; gap: 5px; margin-bottom: 2px; }
.ib-kb-item-badges { display: flex; gap: 3px; flex-shrink: 0; align-items: center; padding-top: 1px; }
.ib-kb-badge {
	display: inline-flex; align-items: center; font-size: 9px; font-weight: 700;
	border-radius: 8px; padding: 1px 5px; white-space: nowrap; letter-spacing: .2px; line-height: 1.5;
}
.ib-kb-badge-steps { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.ib-kb-badge-note  { background: #fdf9f7; color: #b85c3a; border: 1px solid #fcd9c7; }
.ib-kb-badge-tip   { background: #f0fdf4; color: #15803d; border: 1px solid #bbf7d0; }

/* Prev / Next navigation in drawer */
.ib-kb-drawer-nav { display: flex; gap: 6px; width: 100%; }
.ib-kb-nav-btn {
	flex: 1; padding: 7px 10px; border-radius: 7px;
	border: 1.5px solid var(--border-color); background: var(--card-bg);
	color: var(--text-muted); font-size: 11px; font-weight: 600;
	cursor: pointer; transition: all 150ms; text-align: center;
	white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1.4;
}
.ib-kb-nav-btn:hover:not(:disabled) { border-color: var(--kb-primary); color: var(--kb-primary); }
.ib-kb-nav-btn:disabled { opacity: .3; cursor: not-allowed; }

/* Tab count filtered state */
.ib-kb-tab-count.ib-count-filtered { background: var(--kb-primary); color: #fff; }
</style>

<div class="ib-kb">

<!-- Slim top bar -->
<div class="ib-kb-slimbar">
  <span class="ib-kb-slimbar-icon"><iconify-icon icon="lucide:book-open" width="20" height="20"></iconify-icon></span>
  <span class="ib-kb-slimbar-title">Knowledge Base</span>
  <span class="ib-kb-slimbar-stat" id="ib-kb-stat-articles">Loading...</span>
  <div class="ib-kb-search-wrap ib-kb-slimbar-search" id="ib-kb-search-wrap">
    <span class="ib-kb-search-icon"><iconify-icon icon="lucide:search" width="16" height="16"></iconify-icon></span>
    <input type="text" class="ib-kb-search" id="ib-kb-search"
      placeholder="Search articles, workflows, features..."
      autocomplete="off" spellcheck="false" aria-label="Search knowledge base">
    <span class="ib-kb-search-kbd">Ctrl K</span>
    <div class="ib-kb-suggestions" id="ib-kb-suggestions" role="listbox"></div>
  </div>
  <div class="ib-kb-slimbar-more" id="ib-kb-more-toggle">
    <span>More</span><iconify-icon class="chev" icon="lucide:chevron-down" width="13" height="13"></iconify-icon>
  </div>
  <a href="/files/instabiz_knowledge_base.pdf" target="_blank" class="ib-kb-slimbar-pdf">
    <iconify-icon icon="lucide:download" width="13" height="13"></iconify-icon> PDF
  </a>
</div>

<!-- Autocorrect hint -->
<div class="ib-kb-correction" id="ib-kb-correction"></div>

<!-- Collapsible extras: categories, recent, quick links, workflow stepper -->
<div class="ib-kb-more-panel" id="ib-kb-more-panel">

  <!-- Category pills -->
  <div class="ib-kb-cats" id="ib-kb-cats"></div>

  <!-- Recently viewed -->
  <div class="ib-kb-recent" id="ib-kb-recent">
    <span class="ib-kb-recent-label">Recent</span>
    <div id="ib-kb-recent-chips"></div>
  </div>

  <!-- Quick links -->
  <div class="ib-kb-quick-links" id="ib-kb-quick-links">
    <a href="/app/ib-customer-board"     class="ib-kb-quick-link"><span class="icon" style="color:#1a7f37"><iconify-icon icon="lucide:target" width="20" height="20"></iconify-icon></span><span class="label">Customer Board</span></a>
    <a href="/app/ib-stock-dashboard"    class="ib-kb-quick-link"><span class="icon" style="color:#6b21a8"><iconify-icon icon="lucide:package" width="20" height="20"></iconify-icon></span><span class="label">Stock</span></a>
    <a href="/app/quotation/new-quotation-1" class="ib-kb-quick-link"><span class="icon" style="color:#b85c3a"><iconify-icon icon="lucide:file-text" width="20" height="20"></iconify-icon></span><span class="label">New Quotation</span></a>
    <a href="/app/sales-order"           class="ib-kb-quick-link"><span class="icon" style="color:#b85c3a"><iconify-icon icon="lucide:shopping-cart" width="20" height="20"></iconify-icon></span><span class="label">Sales Orders</span></a>
    <a href="/app/ib-document-intake"    class="ib-kb-quick-link"><span class="icon" style="color:#7c3aed"><iconify-icon icon="lucide:bot" width="20" height="20"></iconify-icon></span><span class="label">Document Intake</span></a>
    <a href="/app/ib-main-dashboard"     class="ib-kb-quick-link"><span class="icon" style="color:#006064"><iconify-icon icon="lucide:layout-dashboard" width="20" height="20"></iconify-icon></span><span class="label">Dashboard</span></a>
    <a href="/app/ib-item-pricing"       class="ib-kb-quick-link"><span class="icon" style="color:#b8860b"><iconify-icon icon="lucide:tag" width="20" height="20"></iconify-icon></span><span class="label">Item Pricing</span></a>
    <a href="/app/query-report/IB Daily Sales Report" class="ib-kb-quick-link"><span class="icon" style="color:#1a60b0"><iconify-icon icon="lucide:trending-up" width="20" height="20"></iconify-icon></span><span class="label">Daily Sales</span></a>
  </div>

  <!-- Workflow stepper -->
  <div class="ib-kb-workflow">
    <h3 style="display:flex;align-items:center;gap:8px"><iconify-icon icon="lucide:git-branch" width="15" height="15" style="color:var(--kb-primary)"></iconify-icon>Sales Workflow <small style="font-weight:400;font-size:11px;color:rgba(0,0,0,.5)"> — click a step to learn more</small></h3>
    <div class="ib-kb-flow">
      <div class="ib-kb-flow-step" data-workflow="lead">Lead / Customer</div>
      <div class="ib-kb-flow-arrow">&#8594;</div>
      <div class="ib-kb-flow-step" data-workflow="quotation">Quotation</div>
      <div class="ib-kb-flow-arrow">&#8594;</div>
      <div class="ib-kb-flow-step" data-workflow="so">Sales Order</div>
      <div class="ib-kb-flow-arrow">&#8594;</div>
      <div class="ib-kb-flow-step" data-workflow="dn">Delivery Note</div>
      <div class="ib-kb-flow-arrow">&#8594;</div>
      <div class="ib-kb-flow-step" data-workflow="si">Sales Invoice</div>
      <div class="ib-kb-flow-arrow">&#8594;</div>
      <div class="ib-kb-flow-step" data-workflow="payment">Payment</div>
    </div>
    <div class="ib-kb-wf-detail" id="ib-kb-wf-detail">
      <div class="ib-kb-wf-detail-hdr">
        <h4 id="ib-kb-wf-title">Detail</h4>
        <span class="ib-kb-wf-close" id="ib-kb-wf-close">&#x2715;</span>
      </div>
      <div class="ib-kb-wf-body" id="ib-kb-wf-body"></div>
    </div>
  </div>

</div>

<!-- No results -->
<div class="ib-kb-no-results" id="ib-kb-no-results" style="display:none">
  <span class="nr-icon"><iconify-icon icon="lucide:search-x" width="26" height="26"></iconify-icon></span>
  <p id="ib-kb-no-q">No results found</p>
  <small>Try different keywords or <button id="ib-kb-clear-search">clear search</button></small>
</div>

<!-- Section tabs + content pane -->
<div class="ib-kb-tabbar" id="ib-kb-tabbar"></div>
<div class="ib-kb-pane" id="ib-kb-pane"></div>

</div>`;
}

function _kb_drawer_html() {
	return `
<style>
.ib-kb-overlay {
	display: none;
	position: fixed;
	inset: 0;
	background: rgba(0,0,0,.35);
	z-index: 1040;
	cursor: pointer;
	-webkit-tap-highlight-color: transparent;
}
.ib-kb-overlay.open { display: block; }

.ib-kb-drawer {
	position: fixed;
	right: 0;
	top: 0;
	width: 460px;
	max-width: 94vw;
	height: 100vh;
	background: var(--card-bg);
	border-left: 1px solid var(--border-color);
	box-shadow: -8px 0 40px rgba(0,0,0,.15);
	z-index: 1041;
	display: flex;
	flex-direction: column;
	transform: translateX(100%);
	transition: transform .28s cubic-bezier(.4,0,.2,1);
}
.ib-kb-drawer.open { transform: translateX(0); }

.ib-kb-drawer-hdr {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 14px 18px;
	border-bottom: 1px solid var(--border-color);
	background: var(--bg-color);
	flex-shrink: 0;
}
.ib-kb-drawer-bc {
	flex: 1;
	font-size: 12px;
	color: var(--text-muted);
	display: flex;
	align-items: center;
	gap: 6px;
	flex-wrap: wrap;
}
.ib-kb-drawer-bc .bc-section { font-weight: 700; }
.ib-kb-drawer-bc .bc-arrow { opacity: .5; }
.ib-kb-drawer-bc-icon { display: flex; align-items: center; }
.ib-kb-drawer-close {
	width: 28px;
	height: 28px;
	border-radius: 50%;
	border: 1px solid var(--border-color);
	background: var(--card-bg);
	cursor: pointer;
	font-size: 14px;
	display: flex;
	align-items: center;
	justify-content: center;
	flex-shrink: 0;
	transition: all 200ms ease;
	color: var(--text-color);
}
.ib-kb-drawer-close:hover { background: #fee2d5; border-color: var(--kb-primary); color: var(--kb-primary); }

.ib-kb-drawer-body {
	flex: 1;
	overflow-y: auto;
	padding: 20px 22px;
}
.ib-kb-drawer-body h2 {
	font-size: 17px;
	font-weight: 700;
	margin: 0 0 10px;
	line-height: 1.35;
}
.ib-kb-drawer-body p.desc {
	font-size: 13px;
	color: var(--text-muted);
	line-height: 1.65;
	margin-bottom: 16px;
}

.ib-kb-drawer-footer {
	padding: 14px 22px;
	border-top: 1px solid var(--border-color);
	display: flex;
	gap: 10px;
	flex-wrap: wrap;
	flex-shrink: 0;
	background: var(--bg-color);
}
.ib-kb-drawer-btn {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 8px 16px;
	border-radius: 8px;
	font-size: 13px;
	font-weight: 600;
	cursor: pointer;
	text-decoration: none;
	transition: all 200ms ease;
	border: 1.5px solid;
}
.ib-kb-drawer-btn.primary {
	background: var(--kb-primary);
	border-color: var(--kb-primary);
	color: #fff;
}
.ib-kb-drawer-btn.primary:hover {
	background: var(--kb-primary-dark);
	border-color: var(--kb-primary-dark);
	color: #fff;
}
.ib-kb-drawer-btn.secondary {
	background: var(--card-bg);
	border-color: var(--border-color);
	color: var(--text-color);
}
.ib-kb-drawer-btn.secondary:hover {
	border-color: var(--kb-primary);
	color: var(--kb-primary);
}

/* Related items strip */
.ib-kb-related { margin-top: 22px; }
.ib-kb-related-title { font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .6px; margin-bottom: 8px; }
.ib-kb-related-item {
	display: flex;
	gap: 8px;
	align-items: center;
	padding: 8px 0;
	border-bottom: 1px solid var(--border-color);
	cursor: pointer;
	transition: color 150ms;
}
.ib-kb-related-item:last-child { border-bottom: none; }
.ib-kb-related-item:hover .ri-title { color: var(--kb-primary); }
.ri-title { font-size: 12.5px; font-weight: 600; flex: 1; }
.ri-arrow { font-size: 11px; color: var(--text-muted); }
</style>
<div class="ib-kb-overlay" id="ib-kb-overlay"></div>
<aside class="ib-kb-drawer" id="ib-kb-drawer" role="dialog" aria-modal="true">
  <div class="ib-kb-drawer-hdr">
    <div class="ib-kb-drawer-bc" id="ib-kb-drawer-bc"></div>
    <button class="ib-kb-drawer-close" id="ib-kb-drawer-close" aria-label="Close">&#x2715;</button>
  </div>
  <div class="ib-kb-drawer-body" id="ib-kb-drawer-body"></div>
  <div class="ib-kb-drawer-footer" id="ib-kb-drawer-footer"></div>
</aside>`;
}

// ── KB Data ──────────────────────────────────────────────────────────────────

const _ALL  = ["System Manager","Sales Manager","Sales User","Accounts Manager","Accounts User","HR Manager","HR User","Purchase Manager","Purchase User","Warehouse Manager","Stock User","Factory Management"];
const _SALES    = ["System Manager","Sales Manager","Sales User"];
const _FINANCE  = ["System Manager","Accounts Manager","Accounts User","Sales Manager"];
const _MANAGERS = ["System Manager","Sales Manager","Accounts Manager","HR Manager","Purchase Manager"];
const _HR       = ["System Manager","HR Manager","HR User"];
const _PURCHASE = ["System Manager","Purchase Manager","Purchase User"];
const _STOCK    = ["System Manager","Warehouse Manager","Stock User","Purchase Manager","Purchase User","Sales Manager","Factory Management"];
const _PROD     = ["System Manager","Factory Management","Sales Manager"];
const _AI       = ["System Manager","Sales Manager","Accounts Manager"];
const _ANALYTICS= ["System Manager","Sales Manager","Accounts Manager","HR Manager","Purchase Manager"];

const KB_SECTIONS = [
	{
		id: "access", cat: "access",
		icon: '<iconify-icon icon="lucide:shield-check" width="17" height="17"></iconify-icon>', color: "#f0f4ff", iconColor: "#3b5bdb",
		title: "Workspace Roles & Access",
		roles: _ALL,
		items: [
			{
				num: "ACC-1", title: "Who Sees What — Workspace Shortcuts by Role",
				updated: "2026-08-03",
				desc: "Each of the 6 Instabiz workspaces is itself role-gated (you only see a workspace if you hold one of its roles), and a handful of shortcuts inside a workspace are further restricted on top of that.<br><br><b>Instabiz</b> (Sales User, Sales Manager, System Manager) — almost everything here is open to Sales User too: both dashboards, Customer Board, Item Pricing, Production Tracker, Live Stock Balance, Sales Incentives, Advance Approvals, My HR, Quotation/Sales Order/Customer/Lead/Sales Invoice/Delivery Note/Sample Request/Lead Sales Team, IB Transport, Knowledge Base, and most Reports (Daily Sales, Sales KPIs, Lost Deals, Territory, SKU Sales, Gross Margin, Collections Report, Activity Log, Dispatch Report). Sales User can add a new Transport, State, Campaign, or Customer Group inline from any Link field that uses one (e.g. picking Transport on a Sales Order) — add-only, editing/deleting an existing entry still needs Sales Manager. <b>Sales Manager only</b>: Business Pulse, Customer Health, Customer Board's Team tab, IB Branding, plus the Sales Person Summary and Credit Note Register reports.<br><br><b>Instabiz Finance</b> (Accounts User, Accounts Manager, System Manager) — Finance Dashboard, Collections Dashboard, Bank Import, Payment Entry, Sales Invoice, Journal Entry, Bank Reconciliation Tool, Advance Approvals, Stock, Analytics Hub, Knowledge Base, and Reports: AR Aging, Cash Flow, Bank Recon, Collections Report, Party Outstanding Summary, Credit Note Register, Customer Ledger Summary, General Ledger, Trial Balance. PDC Cheques is Accounts-User-only; Credit Note is Accounts-Manager-only. <b>Purchase-side shortcuts moved out entirely</b> in the 2026-07-24 workspace split — see Instabiz Procurement below.<br><br><b>Instabiz Procurement</b> (Purchase User, Purchase Manager, System Manager) — Procurement Dashboard, Purchase Order/Receipt/Invoice, Debit Note, native Purchase Register / Item-wise Purchase Register, Supplier Ledger Summary, Analytics Hub, Knowledge Base, and Reports: AP Aging, Purchase Pipeline, Debit Note Register. Accounts User/Manager are not in this workspace's role list.<br><br><b>Instabiz HR</b> (HR User, HR Manager, HR Attendance Terminal User, System Manager) — HR Dashboard, Employees, Attendance Terminal, Biometric Import, Checkins, Org Chart, Leave Applications, Salary Slips, F&amp;F Settlement, Hikvision Terminals, Analytics Hub, Knowledge Base, and the Payroll Summary report.<br><br><b>Instabiz Stock</b> (Stock User, Stock Manager, System Manager) — Stock, Inward Stock Transfer, Stock Reconciliation, Analytics Hub, Knowledge Base, and the Stock Ageing report.<br><br><b>Instabiz Production</b> (Factory Production, Factory Management, System Manager) — see the Production Module section of this Knowledge Base.<br><br><b>Instabiz Misc</b> (System Manager only) — Chart of Accounts, Cost Center, System Health, Knowledge Base.",
				tags: "roles access workspace shortcuts who sees what sales manager user accounts procurement purchase hr stock misc factory production",
			},
			{
				num: "ACC-2", title: "Document-Level Permissions (Sales Docs)",
				desc: "Within Sales documents (Quotation, Sales Order, Delivery Note, Sales Invoice), data visibility is further filtered:<br><br><b>Sales User</b> — sees only documents they own or are assigned to (custom_sales_person_user = their email).<br><b>Sales Manager, System Manager</b> — sees all documents across all reps (privileged bypass).<br><br>This applies to List views and reports. Creating a new document auto-assigns it to the logged-in user.",
				tags: "document permission sales user manager visibility isolation data access",
			},
			{
				num: "ACC-3", title: "Role Reference — Who Can Do What",
				desc: "<b>Sales User:</b> Create and manage own Quotations, Sales Orders, Leads, Delivery Notes, Sales Invoices, Sample Requests. View Rate Card and Stock.<br><b>Sales Manager:</b> All of Sales User + view all reps' documents + Reports + Customer Board's Team tab + set Sales Targets.<br><b>Accounts User:</b> Finance shortcuts + Finance Reports. Create Payment Entries, Purchase Invoices, PDC records. Bank Import and Reconciliation.<br><b>Accounts Manager:</b> All of Accounts User + full Finance access.<br><b>HR Manager:</b> Employees, Attendance, Leave, Payroll, Overtime, F&amp;F Settlement. Approve/reject leave applications inline from HR Dashboard.<br><b>Factory Management:</b> Work Orders, Machines, Order Sheets, Production Dashboard (Dashboard + Stages tabs), DPR.<br><b>System Manager:</b> Full access including workspace management, user administration.",
				tags: "role reference what can do sales accounts hr factory system manager permissions",
			},
		],
	},
	{
		id: "sales", cat: "sales",
		icon: '<iconify-icon icon="lucide:shopping-cart" width="17" height="17"></iconify-icon>', color: "#fde8e0", iconColor: "#b85c3a",
		title: "Sales and Quotations",
		roles: _SALES,
		items: [
			{
				num: "2.2", title: "Creating a Quotation",
				desc: "Go to Workspace, Quotation, New. Set Location, Customer or Lead, add items with dimensions. System auto-calculates qty and picks the GST template.",
				link: "/app/quotation/new-quotation-1", linkLabel: "New Quotation",
				tags: "q quote estimate pricing",
				steps: [
					"Go to <b>Workspace, Quotation, New</b>.",
					"Set <b>Location</b> (Maharashtra / Gujarat / Chennai) — auto-sets GSTIN and naming prefix.",
					"Select <b>Quotation To</b>: Customer or Lead.",
					"Add items: enter Width (mm), Length (mtr), Qty/Pkg, Total Pkg. Qty auto-calculates.",
					"Rate auto-applies from Pricing Rules if a rate contract is configured.",
					"System picks GST template (In-state / Out-state) from GSTINs automatically.",
					"Save as Draft, then Submit.",
				],
				tip: "Quotations expire after 1 month. Daily scheduler sends alerts at 15, 7, and 1 day before expiry.",
			},
			{
				num: "2.3", title: "Converting Quotation to Sales Order",
				desc: "Open a submitted Quotation, click Make, Sales Order. Dimensions, transport, and address carry across automatically.",
				link: "/app/quotation", linkLabel: "Quotation List",
				tags: "so convert confirm order",
				steps: [
					"Open a submitted Quotation.",
					"Click <b>Make, Sales Order</b>.",
					"Review — all item dimensions and custom fields are pre-filled.",
					"Submit. Stock is reserved at this point.",
				],
				note: "SO submit is blocked if customer outstanding exceeds the credit limit AND the oldest invoice is past the configured overdue days.",
			},
			{
				num: "2.4", title: "Creating a Delivery Note",
				desc: "From submitted Sales Order, click Make, Delivery Note. Warehouse auto-sets from location. System checks stock and creates a draft Stock Reconciliation if short.",
				link: "/app/delivery-note", linkLabel: "Delivery Notes",
				tags: "dn dispatch ship goods",
				steps: [
					"Open the submitted Sales Order.",
					"Click <b>Make, Delivery Note</b>.",
					"Enter <b>LR Number</b> and <b>Transporter</b>.",
					"If stock is short, a draft Stock Reconciliation is auto-created — submit it first, then re-submit DN.",
					"On DN submit: E-Way Bill auto-generates; sales person gets a bell notification.",
				],
			},
			{
				num: "2.5", title: "Creating a Sales Invoice",
				desc: "From submitted Delivery Note, click Make, Sales Invoice. Inherits the same number (DN IB-BWD-DC-00005 becomes SI IB-BWD-INV-00005). Add transport charges if applicable.",
				link: "/app/sales-invoice", linkLabel: "Sales Invoices",
				tags: "si invoice billing irn einvoice",
				steps: [
					"Open the submitted Delivery Note.",
					"Click <b>Make, Sales Invoice</b>.",
					"Optionally enter <b>Transport Charges</b> — GST on transport is auto-calculated.",
					"Submit. Click <b>Generate e-Invoice</b> button to create the IRN after submission.",
					"Print using <b>IB GST Tax Invoice</b> format for the 2-page output with IRN / QR code.",
				],
			},
			{
				num: "2.7", title: "Editing Items on a Submitted Quotation",
				desc: "Dimension fields, rates, quantities, and amounts can all be changed directly on a submitted Quotation without amending. Item code, location, or adding/removing rows require amendment.",
				tags: "edit submitted quotation item amend change update rate qty",
				steps: [
					"Open the submitted Quotation.",
					"<b>Fields editable directly (no amendment needed):</b> Width (mm), Length (mtr), QTY/PKG, Total PKG, Branding, Marking, Thickness, Color, HSN/SAC, Rate, Qty, Amount. All have <code>allow_on_submit=1</code>.",
					"Use <b>Update Items</b> button or click the field directly in the items table.",
					"Simply click the field, edit, and save.",
					"<b>Fields requiring amendment:</b> Item Code, Quotation To (Customer/Lead), Location, or adding/removing items.",
					"To amend: click <b>Cancel</b> (you must enter a Cancellation Reason), then click <b>Amend</b>.",
					"Amendment creates a new version: <code>IB-BWD-Q-00005-1</code>. The original is locked.",
					"Edit the new amended draft, then re-submit.",
				],
				note: "Transport field on the Quotation header is also directly editable on submitted docs.",
			},
			{
				num: "2.75", title: "Amending a Submitted Sales Order",
				desc: "To change item quantities, rates, or items on a submitted SO: Cancel → Amend. A few fields (Transport, Cancellation Reason, Advance Received) are editable without amendment.",
				tags: "amend so sales order edit item rate qty cancel",
				steps: [
					"Open the submitted Sales Order.",
					"<b>Directly editable fields (no amendment):</b> Transport, Cancellation Reason.",
					"<b>Fields requiring amendment:</b> Item code, qty, rate, adding/removing rows.",
					"Go to SO header, enter <b>Cancellation Reason</b> in the field at the top (required before cancel).",
					"Click <b>Cancel</b>.",
					"Click the <b>Amend</b> button that appears after cancellation.",
					"A new draft SO is created with suffix: <code>IB-BWD-SO-00005-1</code>.",
					"Edit as needed, then re-submit.",
				],
				note: "If a DN or SI already exists against the SO, cancellation is blocked until those child documents are cancelled first.",
			},
			{
				num: "2.76", title: "Attaching a Document to a Single Line Item",
				updated: "2026-07-25",
				desc: "Any item row on a Quotation, Sales Order, Delivery Note, or Sales Invoice can carry its own attachment (artwork proof, packing photo, PO copy) — separate from the document-level Attachments section. Works even after submit.",
				tags: "attach item row document line grid column artwork proof",
				steps: [
					"Open the item's row by clicking the pencil/edit icon at the end of the row (or click the row itself).",
					"In the expanded row editor, find the <b>Document</b> field and click <b>Attach</b>.",
					"Upload the file. Save the row.",
				],
				tip: "The Document field doesn't show as a column in the collapsed grid by default. To add it: click the gear icon (⚙) at the top-right of the item grid → Configure Columns → + Add / Remove Columns → check <b>Document</b> → Update. This is a per-user preference, so each teammate who wants it visible needs to add it once.",
			},
			{
				num: "2.8", title: "Reopening a Cancelled Document",
				desc: "Cancelled Quotations and Sales Orders can be reopened. Blocked if a linked DN or SI still exists.",
				tags: "reopen cancel draft",
				steps: [
					"Open the cancelled document.",
					"Click <b>Reopen</b>.",
					"System resets docstatus to Draft and adds an audit comment.",
				],
			},
			{
				num: "2.9", title: "Default Delivery Date (ETD) on New Sales Orders",
				updated: "2026-07-31",
				desc: "New Sales Orders default their Delivery Date to 8 days after the transaction (order) date. Pick a different date before saving if the real delivery timeline is different — the default only applies if you don't.",
				tags: "etd estimated time of delivery delivery date default sales order 8 days badge color coded new order",
				steps: [
					"Create a new Sales Order — the Delivery Date field pre-fills to 8 days from today's transaction date.",
					"Change it to any other date before saving if needed. Existing Sales Orders are untouched by this default.",
					"Once submitted, this date drives the color-coded <b>ETD</b> badge on each order's card in the Production Dashboard's Active Production Plan (green = on track, orange = due within 2 days, red = overdue) — see PROD-5.",
				],
				note: "This is a default only — it doesn't block or validate anything.",
			},
			{
				num: "26", title: "Margin % on Quotation Items",
				desc: "Each Quotation item shows Margin % auto-calculated: (rate - valuation_rate) / rate x 100. Read-only; updates when rate changes.",
				tags: "margin profit cost",
				note: "Valuation rate is fetched from the Item master when the item code is selected.",
			},
			{
				num: "27", title: "Floor Price Enforcement — Removed 2026-08-04",
				updated: "2026-08-04",
				desc: "Removed entirely — was causing false blocks. There is no floor/margin check on Quotation or Sales Order rate any more; Sales Users can save/submit at any rate. Margin % (item 26 above) still displays for information, it just no longer gates saving.",
				tags: "floor price minimum margin block removed",
			},
			{
				num: "SO", title: "Cancellation Reason Required",
				desc: "Sales Orders, Delivery Notes, and Sales Invoices all require a Cancellation Reason (custom_cancel_reason) before they can be cancelled.",
				tags: "cancel reason block",
			},
			{
				num: "17", title: "Rate Contracts (Customer-Specific Pricing)",
				desc: "Lock agreed rates per customer per item using ERPNext Pricing Rules. The rate auto-applies on Quotation and Sales Order when that customer is selected. No custom code needed — it is a native ERPNext feature.",
				tags: "rate contract customer pricing rule item fixed price agreement special",
				steps: [
					"Go to <b>Accounts → Pricing Rule → New</b> (or search Pricing Rule).",
					"Set <b>Applicable For</b> = Customer. Select the customer.",
					"Set <b>Apply On</b> = Item Code. Select the item.",
					"Set <b>Price or Discount</b> = Rate. Enter the agreed rate.",
					"Set <b>Valid From</b> and <b>Valid Upto</b> for the contract period.",
					"Save. Rate auto-applies whenever that customer+item combination appears on a Q or SO.",
				],
				note: "If the contract rate changes after a Quotation is submitted, the SO carries the Q's old rate. Correct the SO rate manually if needed. The Recalculate Items function reads the row rate as-is and does not overwrite it.",
			},
			{
				num: "46", title: "Packing Specification and IB Packing List",
				desc: "Each Item can have packaging fields: Rolls Per Box, Carton Weight (kg), and Carton Marking (printed on carton). These appear on the IB Packing List print format on Delivery Notes, and (New) directly on the Delivery Note's own item grid too — a <b>Weight (KG)</b> column (boxes × Item Carton Weight, same math as the print format) and the native <b>Batch No</b> column are now both visible in the grid without opening the row editor, no need to print just to see them.",
				tags: "packing list rolls box carton weight marking dn print batch no weight grid column",
				steps: [
					"Open the <b>Item</b> master for a finished good.",
					"Fill in <b>Rolls Per Box</b>, <b>Carton Weight (kg)</b>, <b>Carton Marking</b> (the text to print on cartons).",
					"Save the Item.",
					"On the Delivery Note item grid, <b>Batch No</b> and <b>Weight (KG)</b> now show as columns directly — Weight recalculates automatically on save from Rolls Per Box + Carton Weight.",
					"When a Delivery Note is submitted, select <b>IB Packing List</b> as the print format.",
					"Output includes: item, qty, UOM, rolls/box, number of boxes, carton weight, total weight, carton marking, LR number in header, totals row, and three signature lines.",
				],
			},
			{
				num: "28", title: "Sales Incentives — How Commission Is Calculated",
				updated: "2026-07-29",
				desc: "Open the <b>Sales Incentives</b> page and pick a sales person from the dropdown — nothing calculates until you do. Sales Managers/System Managers can also pick <b>All Sales Reps</b> for a team-wide leaderboard. Sales Users are locked to their own number automatically, no picker needed.",
				link: "/app/ib-sales-incentives", linkLabel: "Sales Incentives",
				tags: "incentive commission slab target collected achievement designation sales manager user calculation formula",
				steps: [
					"<b>Collected</b> for the month = SUM(grand_total) − SUM(outstanding) across that rep's Sales Orders in the selected month (dev mode) — switches to Sales Invoice automatically once real billing goes live (see billing-mode FAQ). \"Outstanding\" here means grand_total minus any advance already paid.",
					"<b>Achievement %</b> = Collected ÷ Target × 100, where Target comes from that rep's <b>IB Sales Target</b> record for the month (set via the Set Targets / per-row ✎ button).",
					"<b>Designation</b> is auto-detected from the rep's Frappe roles: has <b>Sales Manager</b> role → uses the Sales Manager slab table; otherwise → Sales User slab table.",
					"<b>Slab match</b>: the rep's Achievement % is matched against that designation's <b>IB Incentive Slab</b> rows (from_pct ≤ achievement % &lt; to_pct, 0 = no upper bound). The matching row's Commission % applies.",
					"<b>Commission</b> = Collected × matching slab's Commission % ÷ 100. Zero if no slab matches (e.g. no target set, or achievement below the lowest slab's from_pct).",
					"A rep with a target but zero billing this month still shows up (zero-billing row), so a stalled rep is visible rather than silently missing.",
				],
				note: "Slabs and targets are managed by Sales Manager/System Manager via the page's <b>Slabs</b> and <b>Set Targets</b> buttons — both write to real doctypes (IB Incentive Slab, IB Sales Target), not page-local state.",
				tip: "Everything lives in <code>instabiz/instabiz/page/ib_sales_incentives/</code> (ib_sales_incentives.py has the calc: <code>_apply_slab()</code>, <code>_get_slab_designation()</code>, <code>get_incentives_data()</code>) plus <code>instabiz/overrides/sales_target.py</code> (slab/target CRUD) and <code>instabiz/overrides/billing_mode.py</code> (the Sales-Order-vs-Sales-Invoice toggle every figure here respects).",
			},
		],
	},
	{
		id: "payment", cat: "finance",
		icon: '<iconify-icon icon="lucide:credit-card" width="17" height="17"></iconify-icon>', color: "#e0f0ff", iconColor: "#1a60b0",
		title: "Payments and Collections",
		roles: [..._FINANCE, "Sales User"],
		items: [
			{
				num: "3.1", title: "Recording a Payment Against Invoice",
				desc: "Open submitted Sales Invoice, click Make, Payment Entry. Set amount, payment mode, reference number, then submit.",
				link: "/app/payment-entry", linkLabel: "Payment Entries",
				tags: "pe receipt collection money bank",
				steps: [
					"Open the submitted Sales Invoice.",
					"Click <b>Make, Payment Entry</b>.",
					"Set <b>Amount Received</b>, <b>Mode of Payment</b> (Cash / Cheque / Wire Transfer / Bank Draft / Credit Card), <b>Reference No</b>.",
					"Save and Submit.",
				],
				tip: "Accounts roles (Accounts User, Accounts Manager, System Manager) receive a bell notification on Payment Entry submit.",
			},
			{
				num: "3.2", title: "Recording a Payment — Sales Users",
				desc: "Sales Users use a simplified \"Record Payment\" dialog instead of the full Payment Entry form — every field it needs is shown at once, with no conditional fields to figure out.",
				link: "/app/payment-entry", linkLabel: "Payment Entries",
				tags: "record payment simple simplified sales user upi neft rtgs cheque proof screenshot utr statement",
				steps: [
					"From a Draft Sales Order: click <b>Record Advance (Deposit)</b> under Create.",
					"Or from the Payment Entry list: click <b>Record Payment</b> (replaces the standard + Add button for Sales Users).",
					"Fill Customer (your own customers only), Date, Amount Received, Deposit To, Mode of Payment, Cheque/Reference No and Date.",
					"For UPI, NEFT, RTGS, or cheque, attach the screenshot, UTR, or bank statement in <b>Payment Proof</b> — optional but recommended.",
					"Click Save.",
				],
				tip: "A cash receipt with no cheque/UTR number can use \"CASH\" as the Reference No — it's required by accounting for any bank deposit, cash included.",
			},
			{
				num: "3.3", title: "Advance Payment Against Sales Order",
				updated: "2026-07-31",
				desc: "Two different paths depending on whether the Sales Order is still Draft or already submitted — they are not interchangeable. <b>Redesigned 2026-07-31</b>: the original Draft-SO design (Payment Entry referencing a still-Draft SO) was found to have never worked, not once, since it was built — core ERPNext unconditionally rejects a Payment Entry whose Reference table points at a non-submitted Sales Order.",
				link: "/app/payment-entry", linkLabel: "New Payment Entry",
				tags: "advance prepayment so reference approval approve pending confirm deposit record advance custom_advance_for_so draft",
				steps: [
					"<b>Advance on a Draft SO (before submission) — use the \"Record Advance (Deposit)\" button:</b> open the Draft Sales Order → click <b>Record Advance (Deposit)</b> (the native \"Create → Payment\" button never shows on a Draft SO, this is the only path in). Opens a pre-filled on-account Receive Payment Entry — it does <i>not</i> use the SO Reference table at all (new field <code>Payment Entry.custom_advance_for_so</code> instead), so core ERPNext's submitted-SO check never fires.",
					"Save and Submit the Payment Entry. The Sales Order's <b>Advance Approval Status</b> is set to Pending — it cannot be submitted until approved.",
					"The designated approver (or System Manager) opens the Sales Order and clicks <b>Advance → Approve</b> (or Reject, with optional remarks). Only then can the order be submitted. Cancelling the Payment Entry recomputes the advance back to 0.",
					"<b>Advance on an already-submitted SO — use the normal Payment Entry Reference table:</b> Accounts, Payment Entry, New. Payment Type = Receive, Party Type = Customer. Add a row in Payment References: Reference DocType = Sales Order, Reference Name = the (submitted) SO number, enter Allocated Amount, Save and Submit.",
					"Open the submitted Sales Order — the <b>Advance Received</b> (<code>custom_advance_paid</code>) field is now updated automatically. No approval gate applies here — approval is a Draft-SO-only concept.",
				],
				note: "The two paths use different fields on Payment Entry (<code>custom_advance_for_so</code> for pre-submission deposits vs. the native Reference table for post-submission advances) and are summed separately — do not try to use the Reference-table method on a Draft SO, it will throw \"Sales Order X must be submitted\".",
			},
			{
				num: "3.4", title: "Attaching a Payment Screenshot",
				desc: "Use Frappe attachments to upload screenshots or PDFs to any document including Sales Orders and Sales Invoices.",
				tags: "screenshot attachment photo proof",
				steps: [
					"Open the Sales Order or Sales Invoice.",
					"Click the <b>Attachments</b> section at the bottom (or the paperclip icon at top-right).",
					"Click <b>Add Attachment, Upload File</b>.",
					"Select the image or PDF from your device.",
					"Alternatively drag-and-drop the file onto the attachment area.",
				],
				tip: "Files can be attached to any document: Lead, Quotation, SO, DN, SI, Employee, etc.",
			},
			{
				num: "67", title: "Auto-Reconciliation of Payments",
				desc: "When a Payment Entry (Receive) is submitted with no reference rows, the system auto-links to the oldest outstanding Sales Invoices for that customer (FIFO order).",
				tags: "auto reconcile fifo oldest link",
				note: "Excess amount stays unallocated with an orange warning. Reconcile manually via the Frappe Bank Reconciliation Tool if needed.",
			},
			{
				num: "48", title: "Credit Limit Enforcement",
				desc: "Set in Customer, Credit Limit tab. Blocks SO submit when BOTH conditions hold: outstanding exceeds the limit AND the oldest unpaid invoice is older than the configured days.",
				link: "/app/customer", linkLabel: "Customer List",
				tags: "credit limit block outstanding overdue",
			},
			{
				num: "57", title: "Overdue Invoice Alerts (3-Tier)",
				desc: "7 days overdue: bell to sales rep. 15 days: bell to rep and managers. 30 days: bell plus customer blocked from new Sales Orders.",
				tags: "overdue alert notification bell block",
				note: "Block auto-clears when all overdue invoices are paid.",
			},
			{
				num: "60", title: "PDC (Post-Dated Cheque) Tracking",
				desc: "Use IB PDC doctype to track post-dated cheques. Alert sent 3 days before cheque date to Accounts roles and Sales Manager.",
				link: "/app/ib-pdc", linkLabel: "IB PDC List",
				tags: "pdc cheque dated bank",
			},
			{
				num: "136", title: "Sending a Customer Their Outstanding Statement (PDF)",
				desc: "Customer master has an \"Outstanding Statement\" button that opens a printable, downloadable, emailable PDF statement of everything that customer owes — itemized by order/invoice with age and balance, plus a total.",
				link: "/app/customer", linkLabel: "Customer List",
				tags: "outstanding statement pdf send customer email dues balance print",
				steps: [
					"Open the Customer record.",
					"Click <b>View, Outstanding Statement</b>.",
					"A new tab opens with the print preview — use Frappe's own <b>Print</b> (download PDF) or <b>Email</b> button from there.",
				],
				note: "Same dev/prod billing-mode switch as the rest of the app: right now (billing not fully live) it lists open Sales Orders; once <code>ib_billing_mode</code> flips to prod it automatically switches to unpaid Sales Invoices instead — no separate setting to change. Emailing requires a working outgoing Email Account to be configured first (none is set up yet on this site) — downloading/printing the PDF works regardless.",
			},
			{
				num: "162", title: "Collections Priority — Who to Chase Today",
				desc: "A ranked list of customers with money outstanding, most urgent first: amount weighted by how old the oldest unpaid order/invoice is and by the customer’s health score. Each row has a Send reminder link that opens WhatsApp with a polite, pre-filled message.",
				link: "/app/query-report/IB Collections Priority", linkLabel: "Collections Priority",
				tags: "collections priority chase overdue outstanding reminder whatsapp dunning follow up payment",
				steps: [
					"Open <b>Collections Priority</b> from the Instabiz or Instabiz Finance workspace.",
					"Work down from Rank 1. Oldest (days) and Health are colour-coded.",
					"Click <b>Send reminder</b> to open WhatsApp with the message ready, check it, and send.",
				],
				note: "Sales Users see only customers they handle; Accounts and managers see everyone. Uses the same billing-mode basis as AR Aging (open Sales Orders now, unpaid Sales Invoices once <code>ib_billing_mode</code> is prod). The reminder link needs a mobile number on the Customer.",
			},
			{
				num: "164", title: "Credit Block Override on Sales Orders",
				desc: "When credit checks are switched on, a Sales Order for a customer over their credit limit (with an invoice past its allowed days) or 30+ days overdue cannot be submitted. A Sales Manager or System Manager can submit it anyway by filling <b>Credit Override Reason</b>; the reason and who approved it are recorded on the order’s timeline.",
				link: "/app/sales-order", linkLabel: "Sales Orders",
				tags: "credit limit override block overdue sales order manager approve submit",
				note: "The checks are off unless <code>ib_so_credit_checks</code> is set to 1 in site config.",
			},
		],
	},
	{
		id: "returns", cat: "finance",
		icon: '<iconify-icon icon="lucide:rotate-ccw" width="17" height="17"></iconify-icon>', color: "#fce4ec", iconColor: "#880e4f",
		title: "Credit Notes and Debit Notes",
		roles: _FINANCE,
		items: [
			{
				num: "93", title: "IB Credit Note (Custom Doctype)",
				desc: "Dedicated Credit Note doctype (IB-CN-{YYYY}-{#####}) inside Instabiz. Customer-side credit for Sales Return, Rate Difference, or Post Sale Discount. Naming is independent from SI/DN series.",
				link: "/app/ib-credit-note/new-ib-credit-note-1", linkLabel: "New Credit Note",
				tags: "cn credit note return refund customer sales",
				steps: [
					"Go to <b>Finance → Credit Note</b> in the workspace.",
					"Select Company, Customer, Posting Date.",
					"Choose Reason Code: <b>Sales Return</b> / Rate Difference / Post Sale Discount.",
					"Set <b>Against Sales Invoice</b> (mandatory for Sales Return).",
					"System auto-fills items and GST template from the original SI.",
					"Adjust qty/rate as needed. GST applies automatically (CGST+SGST or IGST).",
					"Save → Submit. GL entries post: DR Income Account, DR Output GST / CR AR.",
					"For Sales Return, stock is received back (SLE created).",
				],
				note: "Naming: IB-CN-{YYYY}-{#####}. Roles: Sales User (create/draft), Sales Manager + Accounts Manager (submit/cancel). Total CNs against one SI cannot exceed SI grand total.",
			},
			{
				num: "94", title: "IB Debit Note (Custom Doctype)",
				desc: "Dedicated Debit Note doctype (IB-DBN-{YYYY}-{#####}) inside Instabiz. Supplier-side debit for Purchase Return, Rate Difference, or Post Purchase Discount.",
				link: "/app/ib-debit-note/new-ib-debit-note-1", linkLabel: "New Debit Note",
				tags: "debit note purchase vendor supplier return",
				steps: [
					"Go to <b>Finance → Debit Note</b> in the workspace.",
					"Select Company, Supplier, Posting Date.",
					"Choose Reason Code: <b>Purchase Return</b> / Rate Difference / Post Purchase Discount.",
					"Set <b>Against Purchase Invoice</b> (mandatory for Purchase Return).",
					"System auto-fills items and GST template from the original PI.",
					"Adjust qty/rate as needed. GST ITC is reversed automatically.",
					"Save → Submit. GL entries post: DR AP / CR Expense Account, CR Input ITC.",
					"For Purchase Return, stock is sent back to supplier (SLE created).",
				],
				note: "Naming: IB-DBN-{YYYY}-{#####}. Roles: Purchase User (create/draft), Purchase Manager + Accounts Manager (submit/cancel). Total DNs against one PI cannot exceed PI grand total.",
			},
			{
				num: "71", title: "Credit Note Register Report",
				desc: "Reports, IB Credit Note Register. All SI return credit notes (legacy SI-return flow) with original invoice, customer, return reason, and value.",
				link: "/app/query-report/IB Credit Note Register", linkLabel: "View Report",
				tags: "report credit note register list si return",
			},
			{
				num: "95", title: "Debit Note Register Report",
				desc: "Reports, IB Debit Note Register. All submitted IB Debit Notes with against-PI, supplier, reason code, items, GST, and grand total. Bar chart top suppliers by debit value.",
				link: "/app/query-report/IB Debit Note Register", linkLabel: "View Report",
				tags: "report debit note register list supplier purchase",
			},
		],
	},
	{
		id: "crm", cat: "crm",
		icon: '<iconify-icon icon="lucide:target" width="17" height="17"></iconify-icon>', color: "#e8f5e9", iconColor: "#1a7f37",
		title: "CRM and Lead Management",
		roles: _SALES,
		items: [
			{
				num: "5.1", title: "Creating a Lead",
				desc: "CRM, Lead, New. Enter pincode — city and district auto-fill from India Post API. Lead is auto-assigned to a sales rep via round-robin within the state team.",
				link: "/app/lead/new-lead-1", linkLabel: "New Lead",
				tags: "lead prospect crm new create",
				steps: [
					"Go to <b>CRM, Lead, New</b>.",
					"Fill Lead Name, Mobile No, Email, State.",
					"Enter <b>Pincode</b> — city and district auto-fill from India Post.",
					"Save. Lead is auto-assigned to a rep via round-robin.",
				],
			},
			{
				num: "5.3", title: "Quick Status Change in Lead List",
				desc: "In the Lead List, click the coloured status pill next to a lead row to open a floating status picker. Change status without opening the full form.",
				tags: "status change quick pill list",
			},
			{
				num: "5.4", title: "Logging Activity on a Lead",
				desc: "Open Lead, click Log Activity. Select Activity Type (Call / Meeting / WhatsApp / Email / Visit), Outcome, Notes, Next Follow-Up Date.",
				tags: "log activity call meeting followup note",
				steps: [
					"Open a Lead.",
					"Click <b>Log Activity</b>.",
					"Select Activity Type: Call / Meeting / WhatsApp / Email / Visit.",
					"Select Outcome: Positive / Neutral / Negative / No Answer.",
					"Add Notes and optionally set Next Follow-Up Date.",
					"Save. Entry appears in the Lead timeline.",
				],
			},
			{
				num: "5.6", title: "Converting Lead to Customer",
				desc: "Open Lead, click Make, Customer. Custom mapper carries state, pincode, district, city, and sales person to the new Customer automatically.",
				tags: "convert customer lead mapper territory state",
				steps: [
					"Open the Lead (status: Quoted or Hot).",
					"Click <b>Make, Customer</b>.",
					"Custom mapper carries: State, Pincode, City, District, Sales Person.",
					"New Customer record is created and linked to this Lead.",
				],
			},
			{
				num: "18", title: "Lead Scoring (0 to 100)",
				desc: "Auto-computed daily: Temperature (0 / 30 / 60) plus Status bonus (up to 30) plus Contact completeness (mobile, email, POI, follow-up). Stored in custom_lead_score.",
				tags: "score lead hot warm cold priority",
			},
			{
				num: "22", title: "Win-Back Nudges",
				desc: "Daily scheduler: Open or Replied Quotations with no activity in 14+ days trigger an alert to the rep. Leads in Cold, Contacted, or Warm with no activity in 30+ days also trigger an alert.",
				tags: "nudge alert no activity dormant",
			},
			{
				num: "92", title: "Lead State Auto-Derivation",
				desc: "State is set automatically on Lead save. Priority: (1) GSTIN prefix — first 2 digits map to state (27=Maharashtra, 33=Tamil Nadu, 24=Gujarat). (2) Pincode — India Post API lookup if no GSTIN. To bulk-fix existing leads, run: <code>frappe.call(\"instabiz.overrides.lead.rectify_lead_territories\", {dry_run: 0})</code> from bench console.",
				tags: "territory lead gstin state pincode auto",
			},
			{
				num: "85", title: "IB Activity Log Report",
				desc: "Pulls all lead timeline activity logs (type=Info Comments). Columns: date, lead, customer, activity_type, outcome, notes, actor, next_follow_up. Filters: date range, sales person, activity type, outcome.",
				link: "/app/query-report/IB Activity Log", linkLabel: "View Report",
				tags: "activity log report lead call meeting whatsapp outcome",
			},
			{
				num: "LS-1", title: "Lead Sales Team — Round-Robin Assignment Setup",
				desc: "Lead Sales Team is a custom master that controls which sales rep gets auto-assigned to a new Lead. Each team covers one or more States and has a list of Members (Users). When a Lead is saved, the system matches its State to a team and assigns the next rep in rotation.",
				link: "/app/lead-sales-team", linkLabel: "Lead Sales Team List",
				tags: "lead sales team round robin assignment territory state member user configure setup",
				steps: [
					"Go to <b>Lead Sales Team List</b> (search in top bar or Workspace, CRM).",
					"Create a new team (e.g. 'Maharashtra Sales Team').",
					"Add <b>Members</b>: each row links a User who is a sales rep.",
					"Add <b>States</b>: link each State this team covers.",
					"Save. When a Lead is created with a matching State, the system picks the next member in the rotation automatically.",
					"The rotation index advances per assignment — each rep gets equal turns.",
				],
				note: "If no matching team is found for a Lead's state, the lead is left unassigned. If a member is removed from a team, the rotation resets.",
			},
			{
				num: "16", title: "IB Sample Request — Sample Dispatch Tracker",
				desc: "Track the full lifecycle of product samples from request through dispatch to feedback. Doctype: IB Sample Request (IB-SR-.YYYY.-#####). Status flow: Draft → Work Order Created → Sent → Feedback Received → Converted / Closed.",
				link: "/app/ib-sample-request", linkLabel: "Sample Request List",
				tags: "sample request dispatch feedback converted closed lifecycle free paid",
				steps: [
					"Create <b>IB Sample Request</b>: select Customer, Contact Person, Item, Qty, Sample Type (Free / Paid).",
					"System auto-sets Request Date = today, Assigned To = current user.",
					"Click <b>Mark Work Order Created</b> when production starts the sample.",
					"Click <b>Mark Sent</b> when the sample is dispatched.",
					"Click <b>Record Feedback</b>: enter Outcome (Converted / Not Interested / Follow Up / No Response) and feedback notes.",
					"Click <b>Convert to Order</b> to create a linked Sales Order.",
					"Click <b>Close</b> to close without conversion.",
				],
				note: "Status transitions are validated — cannot skip steps. Outcome and feedback are captured before closing. Related Sales Order is linked via the related_sales_order field.",
			},
		],
	},
	{
		id: "gst", cat: "gst",
		icon: '<iconify-icon icon="lucide:file-text" width="17" height="17"></iconify-icon>', color: "#fff3e0", iconColor: "#e65100",
		title: "GST, E-Invoice and E-Way Bill",
		roles: _FINANCE,
		items: [
			{
				num: "56", title: "E-Invoice (IRN) Generation",
				desc: "Generate IRN via the dedicated Generate e-Invoice button on a submitted Sales Invoice. B2C invoices (no GSTIN) are skipped. Non-blocking — check Error Log on failure.",
				tags: "irn einvoice gst b2b irn qr",
				steps: [
					"Submit the Sales Invoice.",
					"Click the <b>Generate e-Invoice</b> button at the top of the form.",
					"IRN and QR code are fetched from the NIC portal and saved to the invoice.",
					"If it fails, check <b>GST India, e-Invoice Log</b> or <b>Error Log</b> for details.",
				],
				note: "MH GSTIN is LIVE. GJ and TN GSTINs are pending NIC portal registration.",
			},
			{
				num: "29", title: "E-Way Bill Auto-Generation",
				desc: "On Delivery Note submit, E-Way Bill auto-generates if the GST API is enabled. LR number and transporter GSTIN are mapped automatically.",
				tags: "ewb ewaybill eway transport gstin dn",
				steps: [
					"Submit the Delivery Note.",
					"EWB is auto-generated if the India Compliance API is configured.",
					"For manual generation: select DN in list, Actions, Generate E-Way Bill.",
					"Extended dialog lets you choose Transaction Type and address overrides.",
				],
				tip: "Transaction Types: 1=Regular, 2=Bill To-Ship To, 3=Bill From-Dispatch From, 4=Combination.",
			},
			{
				num: "76", title: "GSTR-1 Filing",
				desc: "GST India, GSTR-1 Beta. Select Company, GSTIN, Year, Month, click Recompute. Review B2B / CDNR / HSN. Download Excel or JSON, or upload directly to the portal.",
				tags: "gstr1 filing return b2b hsn",
				steps: [
					"Go to <b>GST India, GSTR-1 Beta</b>.",
					"Select Company, GSTIN, Year, Month.",
					"Click <b>Recompute</b>.",
					"Review B2B, CDNR, and HSN summaries.",
					"Click <b>Upload to GST Portal</b> (requires API enabled).",
				],
			},
			{
				num: "77", title: "GSTR-3B Report",
				desc: "GST India, GSTR 3B Report, New. Select Company, GSTIN, Year, Month, Save. Download JSON for portal upload.",
				tags: "gstr3b return filing json",
			},
			{
				num: "78", title: "GSTR-2B Download and Match",
				desc: "GST India, Purchase Reconciliation Tool. Download GSTR-2B via API or manual JSON upload. Auto-matches against submitted Purchase Invoices.",
				tags: "gstr2b purchase reconciliation input tax credit itc",
			},
			{
				num: "70", title: "IB GST Tax Invoice Print Format",
				desc: "2-page print format on Sales Invoice: Page 1 = Tax Invoice with IRN and QR code, bank details, amount in words. Page 2 = E-Way Bill with EWB QR, goods, transport, vehicle details.",
				tags: "print tax invoice format irn qr eway",
			},
			{
				num: "114", title: "GST Accounts Are Shared, Not Per-Location — Cost Center Tracks the Split",
				desc: "All 3 GSTINs (Chennai, Gujarat, Maharashtra) post CGST/SGST/IGST to the same single set of ledger accounts — India Compliance does not allow separate GST account sets per location under one Company. Location-wise tracking instead runs through Cost Center: every Q/SO/DN/SI, PO/PR/PI, and IB Credit/Debit Note tax row now carries the correct location Cost Center (Maharashtra - IB / Gujarat - IB / Chennai - IB), not just the item rows.",
				tags: "gst cost center location multi-gstin chennai gujarat maharashtra chart of accounts reconciliation",
				steps: [
					"To see GST payable/collected split by location: open <b>General Ledger</b> or <b>Trial Balance</b>.",
					"Filter by <b>Cost Center</b> = Maharashtra - IB / Gujarat - IB / Chennai - IB.",
					"Filter Account to an Output/Input CGST, SGST, or IGST account to see that location's GST activity only.",
				],
				note: "Applies going forward only — GL entries posted before 2026-07-29 still show cost center \"Main - IB\" regardless of location and are not retroactively corrected (same approach used for the per-location stock account split).",
			},
		],
	},
	{
		id: "reports", cat: "reports",
		icon: '<iconify-icon icon="lucide:bar-chart-2" width="17" height="17"></iconify-icon>', color: "#e0f7fa", iconColor: "#006064",
		title: "Reports and Analytics",
		roles: _ANALYTICS,
		items: [
			{
				num: "24", title: "IB Daily Sales Report",
				desc: "Single-day snapshot per rep: new leads, quotations, orders, dispatches, MTD revenue vs target. 8 summary cards including Collections Today and Order Backlog.",
				link: "/app/query-report/IB Daily Sales Report", linkLabel: "View Report",
				tags: "daily sales report rep kpi mtd target collections order backlog",
				steps: [
					"Go to <b>Reports → IB Daily Sales Report</b>.",
					"Date filter defaults to today. Change to review any past day.",
					"Click <b>Refresh</b> to load per-rep breakdown (New Leads, Q count+value, SO count+value, Dispatches, MTD Revenue, MTD Target, MTD %).",
					"Summary cards at top: Orders Today, Order Value, Dispatched Today, Collections Today (company-wide), New Leads, Order Backlog, MTD Revenue, MTD vs Target %.",
					"Bar chart shows top reps by today's order value.",
				],
				tip: "Collections Today sums all Payment Entries submitted today company-wide — useful for end-of-day finance review.",
			},
			{
				num: "23", title: "IB Sales KPIs",
				desc: "Per-rep metrics: Leads, Quotations, Orders, Lead-to-Q%, Q-to-SO%, Lead-to-SO%, Revenue, Avg Deal Size, Lost Deals. Bar chart with summary cards.",
				link: "/app/query-report/IB Sales KPIs", linkLabel: "View Report",
				tags: "kpi sales rep performance conversion lead quotation order revenue deal size lost",
				steps: [
					"Go to <b>Reports → IB Sales KPIs</b>.",
					"Set <b>from_date / to_date</b> for the period (default: current month).",
					"Optional: filter by <b>State</b>, <b>Sales Person</b>, or <b>Source</b>.",
					"Click Refresh. Each row = one rep. Conversion % columns color-coded: green ≥30%, orange ≥15%, red <15%.",
					"Bar chart shows top-10 reps by revenue. Summary cards show aggregate totals.",
				],
			},
			{
				num: "64", title: "IB Gross Margin",
				desc: "Per-item: qty sold, revenue, COGS (from Item valuation rate), gross profit, margin %. Color-coded: green at 30%+, orange at 15%+, red below 15%.",
				link: "/app/query-report/IB Gross Margin", linkLabel: "View Report",
				tags: "margin profit cogs item revenue gross profit valuation rate color coded",
				steps: [
					"Go to <b>Reports → IB Gross Margin</b>.",
					"Set date range. Filter by state, item group, or sales person if needed.",
					"Refresh. COGS = <code>qty_sold × Item.valuation_rate</code> (Item master rate, not SI valuation_rate).",
					"Margin % column: green ≥30%, orange ≥15%, red <15% — identifies unprofitable SKUs.",
					"Bar chart shows Revenue vs Gross Profit for top 10 items.",
				],
				note: "Margin uses Item master valuation_rate, not the landed cost on each invoice. Update Item valuation_rate if average cost changes.",
			},
			{
				num: "58", title: "IB AR Aging",
				desc: "Outstanding Sales Invoices bucketed into 0-30, 31-60, 61-90, 90+ days. Color-coded for old invoices. Filter by customer, state, sales person.",
				link: "/app/query-report/IB AR Aging", linkLabel: "View Report",
				tags: "ar aging outstanding overdue receivable bucket 90 days customer",
				steps: [
					"Go to <b>Reports → IB AR Aging</b>.",
					"Filter by customer, state, or sales person as needed.",
					"Click Refresh. Each row = one Sales Invoice. Age column = days since posting date.",
					"90+ bucket colored red. Summary cards: total count, unique customers, total outstanding, 90+ amount.",
					"Use this to prioritize collection calls — sort by 90+ bucket descending.",
				],
			},
			{
				num: "69", title: "IB Collections Report",
				desc: "Per-rep: invoiced, collected, outstanding, collection %. 3-dataset bar chart (Invoiced / Collected / Outstanding). Filter by date, state, sales person.",
				link: "/app/query-report/IB Collections Report", linkLabel: "View Report",
				tags: "collections report rep invoiced outstanding collection percent bar chart",
				steps: [
					"Go to <b>Reports → IB Collections Report</b>.",
					"Set date range (defaults: month start → today). Filter by state, sales person, or chart type.",
					"Refresh. Per-rep row: invoice count, invoiced ₹, collected ₹ (grand_total − outstanding), outstanding ₹, collection % (green ≥75%, orange ≥40%, red <40%).",
					"3-dataset bar chart: Invoiced / Collected / Outstanding per rep.",
					"Summary cards: Total Invoiced, Collected, Outstanding, Overall Collection %.",
				],
			},
			{
				num: "80", title: "IB Cash Flow Statement",
				desc: "GL-entry based: inflows and outflows by category (Collections, Vendor Payments, Salaries, Operating, Tax). Running balance column.",
				link: "/app/query-report/IB Cash Flow Statement", linkLabel: "View Report",
				tags: "cash flow statement inflow outflow balance gl entry bank hdfc payment salary operating tax",
				steps: [
					"Go to <b>Reports → IB Cash Flow Statement</b>.",
					"Filter: bank_account (blank = all 3 HDFC accounts), from_date, to_date, chart_type.",
					"Refresh. Each row = one GL entry on a bank account. Inflow green, outflow red. Running balance column.",
					"Categories auto-derived: Customer collections, Vendor payments, Salary & Wages, Operating Expenses, Financing, Tax Payments, Inter-account.",
					"Summary cards: Opening Balance, Total Inflows, Total Outflows, Net Cash Flow, Closing Balance.",
				],
			},
			{
				num: "86", title: "IB Purchase Pipeline Report",
				desc: "Submitted Purchase Orders with linkage to GRN (receipt) and Purchase Invoice status. See which POs are pending receipt or billing. Filters: date range.",
				link: "/app/query-report/IB Purchase Pipeline", linkLabel: "View Report",
				tags: "purchase pipeline po grn pi receipt billing pending supplier overdue",
				steps: [
					"Go to <b>Reports → IB Purchase Pipeline</b>.",
					"Set from_date and to_date to scope to a PO period.",
					"Refresh. Each row = one submitted PO with its GRN status and PI status.",
					"Use this to find POs with no GRN (not yet received) or GRN-done but PI not raised.",
					"Cross-reference with PO Follow-Up Alerts (feature #30) — those also flag POs >7 days with no GRN.",
				],
			},
			{
				num: "TIP", title: "Changing Report Chart Type",
				desc: "All custom reports have a Chart Type filter: Bar / Pie / Donut / Line / Percentage. Change it and re-run to switch the chart style.",
				tags: "chart bar pie donut line report filter chart type",
				steps: [
					"Open any IB custom report.",
					"Find the <b>Chart Type</b> filter (dropdown, default Bar).",
					"Select Bar / Pie / Donut / Line / Percentage.",
					"Click <b>Refresh</b> to redraw the chart in the new style.",
				],
			},
			{
				num: "62", title: "IB Territory Report",
				desc: "Per-state breakdown: leads, quotations, orders, revenue, avg deal size, lead-to-SO conversion % (color-coded green ≥30% / orange ≥15% / red <15%), lost leads. Bar chart with Revenue and Orders datasets. Filters: from_date, to_date.",
				link: "/app/query-report/IB Territory Report", linkLabel: "View Report",
				tags: "territory state report leads orders revenue conversion rate lost deals geographic performance",
				steps: [
					"Go to <b>Reports → IB Territory Report</b>.",
					"Set date range. Refresh.",
					"Each row = one state. Conversion % = Lead-to-SO %; green ≥30%, orange ≥15%, red <15%.",
					"Bar chart shows Revenue and Orders per state.",
					"Use this to identify under-performing states or allocate more reps.",
				],
			},
			{
				num: "63", title: "IB SKU Report",
				desc: "Per-item: item code, item name, item group, UOM, orders count, qty sold, revenue, avg rate, number of unique customers. Bar chart top 10 by revenue. Filters: from_date, to_date, state, item group.",
				link: "/app/query-report/IB SKU Report", linkLabel: "View Report",
				tags: "sku item report revenue qty sold customers top items product group territory state",
				steps: [
					"Go to <b>Reports → IB SKU Report</b>.",
					"Set date range. Optionally filter by state or item group.",
					"Refresh. Per-item row: orders count, qty sold, revenue, avg rate, unique customers.",
					"Bar chart shows top 10 SKUs by revenue.",
					"Use this to identify fast-movers vs slow-movers; cross-reference with IB Gross Margin for profitability.",
				],
			},
			{
				num: "25", title: "IB Lost Deal Analysis",
				desc: "Lost Leads (custom_status=Lost) and lost Quotations (status=Lost) in one report. Columns: source, loss reason, sales person, state, month, count, value lost, doc link. Bar chart by loss reason. Filters: date range, source, loss reason, state, sales person.",
				link: "/app/query-report/IB Lost Deal Analysis", linkLabel: "View Report",
				tags: "lost deal analysis report lead quotation loss reason source why churn competitor price",
				steps: [
					"Go to <b>Reports → IB Lost Deal Analysis</b>.",
					"Set date range. Filter by source, loss_reason, state, or sales_person as needed.",
					"Refresh. Each row = one lost Lead or lost Quotation. Click the doc link to open the original.",
					"Bar chart shows loss count by reason (Price / Competitor / No Budget / Product / etc.).",
					"Use loss reason trends to guide product or pricing decisions.",
				],
			},
			{
				num: "54", title: "IB Dispatch Report",
				desc: "Per-Delivery-Note for a date: customer, location (derived from warehouse), transporter, LR number, items summary, qty, value, sales person. Bar chart by transporter. Summary: dispatch count, total qty, total value, transporter count. Filters: date, warehouse, sales person.",
				link: "/app/query-report/IB Dispatch Report", linkLabel: "View Report",
				tags: "dispatch report dn delivery note transporter lr number location qty date daily",
				steps: [
					"Go to <b>Reports → IB Dispatch Report</b>.",
					"Set <b>date</b> (default today). Filter by warehouse or sales person if needed.",
					"Refresh. Each row = one Delivery Note. Location derived from set_warehouse (MH/GJ/CN).",
					"Summary: total dispatch count, total qty, total value, unique transporters.",
					"Bar chart shows dispatch qty by transporter.",
				],
			},
			{
				num: "73", title: "IB Sales Person Summary",
				desc: "Per-rep summary from submitted SOs: order count, total revenue, avg order value, max order value. Sales person name resolved from custom_sales_person → User full_name. Filters: from_date, to_date, sales_person_user, status, state.",
				link: "/app/query-report/IB Sales Person Summary", linkLabel: "View Report",
				tags: "sales person summary rep revenue orders performance avg max order value",
				steps: [
					"Go to <b>Reports → IB Sales Person Summary</b>.",
					"Set date range. Filter by sales_person_user, status, or state.",
					"Refresh. Each row = one rep: order count, total revenue, avg order value, max order value.",
					"Use alongside IB Sales KPIs for a complete rep performance picture.",
				],
			},
			{
				num: "72", title: "IB Payroll Summary",
				desc: "Per-employee payroll breakdown using the active salary structure. Computes Basic, HRA, CA, Gross, PF, ESIC, PT, Net — mirroring IB Payroll and Astro Payroll formulas. Supports payroll month filter with proration for absent days. Filters: payroll_month, emp_category (All / Factory / Office), salary_structure.",
				link: "/app/query-report/IB Payroll Summary", linkLabel: "View Report",
				tags: "payroll summary report employee salary basic hra pf esic net factory office prorate absent",
				steps: [
					"Go to <b>Reports → IB Payroll Summary</b>.",
					"Set <b>payroll_month</b> (first of the month). Filter emp_category: All / Factory / Office. Select salary_structure if needed.",
					"Refresh. Per-employee row: Basic, HRA, CA, Gross, PF, ESIC, PT, Net (all computed from structure formulas).",
					"If payroll_month set: amounts prorated by present_days / days_in_month (IB Payroll gives 2-day leave credit).",
					"Use this for payroll review before processing salary slips in HRMS.",
				],
				note: "Factory = department name containing 'Factory'. Absent days: submitted Salary Slips first, then Attendance records.",
			},
			{
				num: "PS-1", title: "IB Price Suggestions — Weekly Pricing Recommendations (New, 2026-08-10)",
				updated: "2026-08-10",
				desc: "Every week, compares each item's recent selling price against its actual sales velocity and margin target, and flags items where the price looks out of step — either too high (losing deals) or too low (leaving margin on the table).",
				link: "/app/query-report/IB Price Suggestions", linkLabel: "View Report",
				tags: "price suggestions recommendation velocity margin deviation weekly item pricing review needs review",
				steps: [
					"Go to <b>Reports → IB Price Suggestions</b> (Sales workspace).",
					"Each row: item, current price, suggested price, deviation %, demand trend, margin, status.",
					"Rows flagged <b>needs_review</b> deserve a closer look before the next quote goes out.",
					"Status starts as <b>New</b> — mark Applied once you've acted on a suggestion, or Dismissed if it doesn't apply.",
				],
				note: "Suggestions don't change any live rate automatically — this is a review list, not an auto-repricer.",
			},
			{
				num: "PS-2", title: "IB Price History Report — Exportable Per-Item Sales Price History",
				desc: "Same per-item historical selling-price data already available on the Item Pricing page, in an exportable/filterable report format — useful for pulling a price history into a spreadsheet for a customer negotiation or audit.",
				link: "/app/query-report/IB Price History Report", linkLabel: "View Report",
				tags: "price history report export item sales order rate historical",
				steps: [
					"Go to <b>Reports → IB Price History Report</b>.",
					"Filter by item, customer, state, or date range.",
					"Export to Excel/CSV directly from the report toolbar.",
				],
			},
		],
	},
	{
		id: "stock", cat: "stock",
		icon: '<iconify-icon icon="lucide:package" width="17" height="17"></iconify-icon>', color: "#f3e8ff", iconColor: "#6b21a8",
		title: "Stock and Inventory",
		roles: _STOCK,
		items: [
			{
				num: "163", title: "Replenishment Suggestions — What to Reorder",
				desc: "Lists stock items that will run short: daily demand from Sales Orders (recent month weighted more), projected stock across warehouses, days of cover, reorder point and a suggested order quantity. Nothing is ordered automatically.",
				link: "/app/query-report/IB Replenishment Suggestions", linkLabel: "Replenishment",
				tags: "replenishment reorder forecast demand stockout material request purchase suggest",
				steps: [
					"Open <b>Replenishment</b> from the Instabiz Stock or Instabiz Procurement workspace.",
					"Red Days of Cover means stock runs out before a new order can arrive.",
					"Tick the rows to order and click <b>Create Material Request</b>; review the draft, set the warehouse, and save.",
				],
				note: "Reorder point = daily demand × lead time + safety stock (both from the Item; lead time defaults to 14 days if not set). Suggested qty covers lead time plus a 7-day review cycle.",
			},
			{
				num: "9", title: "Stock — Balance + Ledger (merged 2026-08-05)",
				desc: "Workspace, Live Stock Balance. One page, two tabs, replacing the previously separate Stock Dashboard and Stock Ledger pages/shortcuts.<br><b>Balance tab</b>: real-time stock across 3 warehouses with multi-token search, color dots, warehouse breakdown popover, CSV export, and WebSocket live updates. Clicking a row's breakdown popover has a \"View Stock Ledger →\" link that jumps straight to the Ledger tab pre-filtered to that item.<br><b>Ledger tab</b>: full Stock Ledger Entry browser — date range presets, item/warehouse/customer/voucher-type filters, running In/Out/Balance per movement, CSV export.",
				link: "/app/ib-stock-dashboard", linkLabel: "Open Stock",
				tags: "stock live dashboard warehouse balance qty ledger sle movements history merged combined centralize",
			},
			{
				num: "53", title: "Stock Ageing Report",
				desc: "Reports, IB Stock Ageing. Per-item and warehouse: qty, first receipt date, age in days, buckets 0-30 / 31-60 / 61-90 / 90+, valuation rate, stock value.",
				link: "/app/query-report/IB Stock Ageing", linkLabel: "View Report",
				tags: "ageing stock age old report",
			},
			{
				num: "STK-TRACE-1", title: "Traceability — Imported / Purchased Material → Production → Finished Units",
				desc: "One scannable chain from raw material arrival to the box on the customer's dock. <b>Genealogy roots:</b> submitting an <b>IB Container Import</b> (imports) or a <b>Purchase Receipt</b> (domestic purchase) creates one <b>IB Batch</b> per line, tagged <i>Raw Material</i> with the supplier lot, GSM/width, and a link back to the source document. <b>Production:</b> when a Work Order stage is started you can pick that RM batch as the Source Batch; it carries forward automatically to every later stage of the same item. <b>Finished units:</b> completing the final stage creates a Finished-Good IB Batch plus one <b>IB FG Serial</b> per physical box/roll (count = the Work Order's Logs/Pcs-to-Make), each stamped with the full chain.<br><b>Traceability page</b> (Stock / Production workspace): type or scan a Batch, Work Order, or Serial id — see the whole chain both directions, from supplier lot forward to every customer, or from a shipped unit back to its supplier lot.<br>This is a reporting/annotation layer — it does <b>not</b> change how stock moves; you never have to pick a batch on a Delivery Note.",
				link: "/app/ib-trace", linkLabel: "Open Traceability",
				tags: "trace traceability batch serial genealogy lineage lot recall container import purchase receipt grn work order finished good qr scan",
			},
			{
				num: "STK-TRACE-2", title: "Labels — Barcode vs QR, and Scanning",
				desc: "Every label (container box + finished-unit serial) carries <b>both</b> a barcode and a QR, doing different jobs:<br><b>Barcode (Code128)</b> = the id string. A warehouse <b>handheld laser scanner</b> reads it straight into the Scan Stock page's input.<br><b>QR</b> = a link to the Traceability page for that batch/serial. A <b>phone camera</b> scan opens the full trace — for anyone without a handheld scanner (auditor, manager, customer).<br><b>Scan Stock page</b>: scanning a SKU barcode → add/deduct stock as before; scanning an IB Batch or IB FG Serial → shows what it is + an <i>Open Traceability</i> button (trace-only, no stock change).<br><b>Generate Missing Barcodes</b> button on the Item list (Stock Manager / System Manager) gives every stock SKU a Code128 barcode = its own item code, so the whole catalogue is scannable. The barcode also shows, with its scannable image, on the Item form's Details tab.",
				link: "/app/ib-stock-scan", linkLabel: "Open Scan Stock",
				tags: "barcode qr code128 label scan handheld phone camera generate missing item barcode",
			},
			{
				num: "28", title: "Reorder Alerts",
				desc: "Daily scheduler: when bin qty is at or below reorder level, a bell notification goes to Purchase Manager, Purchase User, and System Manager. 7-day cooldown prevents repeat alerts.",
				tags: "reorder alert low stock purchase notification",
			},
			{
				num: "36", title: "Batch Expiry Alert",
				desc: "Daily scheduler: batches expiring within 30 days trigger a bell to Warehouse Manager, Stock User, and Purchase Manager. 7-day cooldown.",
				tags: "batch expiry alert expire warehouse",
			},
			{
				num: "12", title: "Item Pricing (Price List + Item History, merged 2026-08-05)",
				desc: "Page: Item Pricing (<b>Workspace → Item Pricing</b>) — one page, two tabs, replacing the previously separate IB Rate Card and Item Price History pages/shortcuts.<br><b>Price List tab</b>: <b>Jumbo Roll</b> — Face Price and Last Price per SQMT, colour dots, spec tags, UOM chips. <b>Cut Pack</b> — 5 price slabs: Slab 1 (highest / small qty, blue) → Slab 2 (purple) → Slab 3 (orange) → Slab 4 (green) → Slab 5 (bulk best, teal). Face price = Slab 1, Last price = Slab 5, auto-synced on save. Multi-token search with highlight across both tabs. Every row now also has a <b>trending-up icon</b> — jumps straight to that item's actual sold-price history on the Item History tab.<br><b>Item History tab</b>: pick an Item (+ optional Customer) → every past submitted Sales Order line for it, KPI cards (last/lowest/highest rate), rate trend chart, CSV export. Now also shows a <b>Current Rate Card Price</b> card at the top (live, not cached) whenever the selected Item has a matching rate card entry, with a link back to the Price List tab. Picking only a Customer (no Item) also computes the KPI cards — a yellow note discloses that those numbers are blended across every item sold to that customer, not one item's price history.<br><b>How the two are linked</b>: Rate Card entries key on a base spec code (e.g. <code>IS-55113V</code>); real Items append a colour/width/pack suffix (e.g. <code>IS-55113V-300BKRBNL</code>) — there is no exact match between the two tables, only a prefix relationship (confirmed: ~84% of rate card entries have at least one matching real Item this way). A rate card entry with no matching sold Item yet simply shows no sold-history link — not an error.<br><b>Access:</b> Sales User, Sales Manager, System Manager can view both tabs (widened from Sales-Manager-only on the old Price List page, 2026-08-05, at user's request). Sales Manager can Add Entry (toolbar), edit any row (✏), and view full price-change history (🕐) on the Price List tab. System Manager can also delete. All price edits are logged automatically.",
				link: "/app/ib-item-pricing", linkLabel: "Open Item Pricing",
				tags: "rate card price list item pricing item price history jumbo cut pack slab edit history add entry face last price slab1 slab2 slab3 slab4 slab5 sold history current rate merged combined centralize",
				steps: [
					"Go to <b>Workspace → Item Pricing</b>.",
					"<b>Price List tab</b>: switch <b>Jumbo Rolls</b> (FP / LP) or <b>Cut Pack</b> (Slab 1–5); search bar for multi-token filtering (e.g. '100 white self').",
					"Click the <b>trending-up icon</b> on any row to jump to that item's actual sold price history.",
					"<b>Sales Manager+:</b> Click <b>Add Entry</b> toolbar button to create a new entry; click ✏ to edit a row; click 🕐 for that row's price-change history.",
					"<b>System Manager only:</b> Click 🗑 to delete an entry.",
					"<b>Item History tab</b>: pick an Item (and optionally a Customer) to see its Current Rate Card Price card, KPI cards, rate trend, and full Sales Order line history; use date presets / filters / CSV export as needed.",
				],
				note: "Both tabs share one Frappe page/toolbar — switching tabs rebuilds the toolbar for whichever view is active, so bookmarked URLs look like <code>/app/ib-item-pricing</code> (Price List) or <code>/app/ib-item-pricing/item_history</code> (Item History).",
			},
			{
				num: "96", title: "Inward Stock Transfer",
				desc: "Workspace → Instabiz Stock → Inward Stock Transfer. Direct link into the standard Stock Entry list filtered to Purpose = Material Transfer, for warehouse-to-warehouse internal moves (e.g. factory to branch warehouse).",
				link: "/app/stock-entry?purpose=Material Transfer", linkLabel: "Open Inward Stock Transfer",
				tags: "inward stock transfer material transfer warehouse move internal branch",
				steps: [
					"Go to <b>Workspace → Instabiz Stock → Inward Stock Transfer</b>.",
					"Click New to create a Stock Entry with Purpose already set to Material Transfer.",
					"Set Source Warehouse and Target Warehouse, add items and quantities, Submit.",
				],
				note: "This is a plain workspace shortcut into the standard ERPNext Stock Entry doctype — no custom fields, approval stage, or notification behind it. It uses the same permissions and validations as any other Stock Entry.",
			},
			{
				num: "135", title: "Container Import — Labels + Barcode/QR + Batching (New)",
				desc: "Workspace → Instabiz Stock → Container Import. When a container of imported materials arrives: fill container no, supplier, warehouse and import date, then list each SKU with no. of boxes and qty per box. On save, a barcode is auto-resolved per item (reuses the Item's existing barcode if one exists, else generates a new Code128 from the item code and saves it back onto the Item master for future reuse). On Submit: a real Stock Entry (Material Receipt) is posted for every item into the chosen warehouse; items with Batch Tracking enabled (see #34) each get a real new Batch created and linked back to the container; an optional per-row Costing Rate feeds the Stock Entry's valuation if filled. <b>Print All Labels</b> (standard print button) generates one physical label per box — company header, item code + full item mark, item name, sizes (from Item Width/Length), color, qty/ctn, roll no (box N of total), weight, batch no, plus both a barcode and a QR code — matching the paper label format already used on the factory floor. A per-row <b>Reprint Labels</b> grid button re-prints just one item's boxes.",
				link: "/app/ib-container-import/new", linkLabel: "New Container Import",
				tags: "container import label barcode qr code batch batching stock receipt material receipt scan sku box carton roll",
				steps: [
					"Go to <b>Workspace → Instabiz Stock → Container Import → New</b>.",
					"Fill Container No, Supplier, Warehouse, Import Date.",
					"Add one row per SKU: Item Code, No. of Boxes, Qty per Box (Costing Rate optional).",
					"Save — barcode auto-resolves per row.",
					"Submit — posts a Stock Entry (Material Receipt) and creates Batches for any batch-tracked items.",
					"Use the standard <b>Print</b> button (IB Container Label format) to print all labels, or the grid's <b>Reprint Labels</b> button for just one item.",
				],
				note: "Costing Rate is optional — if left blank, the Stock Entry falls back to the Item's existing valuation the same as any manual Material Receipt would.",
			},
			{
				num: "136", title: "Scan Stock — Barcode Add/Deduct (New)",
				desc: "Workspace → Instabiz Stock → Scan Stock. A simple scan-first page for adjusting stock with a handheld/USB barcode scanner: scan or type a barcode (from a Container Import label or any Item Barcode), it resolves to the Item, pick a Warehouse and Qty, then Add (posts a Material Receipt) or Deduct (posts a Material Issue). Works for any item's barcode, not just ones printed from Container Import. A running log of this session's scans (with a link to each Stock Entry) is shown below.",
				link: "/app/ib-stock-scan", linkLabel: "Open Scan Stock",
				tags: "scan stock barcode add deduct receipt issue warehouse qty",
				steps: [
					"Go to <b>Workspace → Instabiz Stock → Scan Stock</b>.",
					"Scan or type a barcode, press Enter.",
					"Pick a Warehouse and enter Qty.",
					"Click <b>Add (Receipt)</b> or <b>Deduct (Issue)</b> — posts and submits a Stock Entry immediately.",
				],
				note: "Stock User, Stock Manager and System Manager roles only. Only works for an item that already has a barcode — today that means items received through Container Import (barcode auto-generated there). An item that has never passed through Container Import has no barcode yet, so scanning it here shows \"No item found for barcode\" — that's not an error, it just hasn't been generated for that item.",
			},
		],
	},
	{
		id: "hr", cat: "hr",
		icon: '<iconify-icon icon="lucide:users" width="17" height="17"></iconify-icon>', color: "#e8f5e9", iconColor: "#1a7f37",
		title: "HR, Attendance and Payroll",
		roles: _HR,
		items: [
			{
				num: "4", title: "Employee Self-Service Check-In",
				desc: "Employees go to /checkin. Select name, click Check-In or Out. Late or early entry triggers a reason dialog stored in Employee Checkin.",
				link: "/checkin", linkLabel: "Open Check-In Portal",
				tags: "checkin checkout attendance employee portal",
			},
			{
				num: "LA-1", title: "Applying for Leave",
				desc: "Employees submit Leave Applications via the Leave Application doctype. Leave types: Casual Leave, Sick Leave, Privilege Leave, Compensatory Off, Leave Without Pay, Maternity Leave, Paternity Leave. HR Manager or designated leave approver approves or rejects. Balance deducted on approval.",
				link: "/app/leave-application/new", linkLabel: "New Leave Application",
				tags: "leave apply application casual sick privilege maternity paternity lwp compensatory off approve reject balance hr manager",
				steps: [
					"Go to <b>Workspace → HR → Leave Application → New</b>.",
					"Select <b>Leave Type</b> (Casual Leave, Sick Leave, Privilege Leave, Compensatory Off, LWP, Maternity, Paternity).",
					"Set <b>From Date</b> and <b>To Date</b>. Total leave days auto-computes (excluding holidays and weekends).",
					"Enter <b>Reason</b> (optional but recommended).",
					"Save. Status becomes Open.",
					"Submit the Leave Application to send it to the approver queue.",
					"HR Manager reviews pending leaves from <b>HR Dashboard → Leaves tab</b> or directly from the Leave Application list.",
					"On Approve: status = Approved, leave balance deducted, Attendance for those days marked as On Leave.",
					"On Reject: status = Rejected, balance unchanged.",
				],
				note: "Leave balance for each leave type is visible in <b>My HR → Leave Summary</b>. You cannot apply for more leaves than your allocation. Half-day leaves: tick the Half Day checkbox and select which half (First/Second).",
				tip: "HR Manager can approve leaves inline from the HR Dashboard → Leaves tab without opening each application individually.",
			},
			{
				num: "31", title: "Auto-Absent Marking",
				desc: "Daily: marks yesterday Absent if no Attendance record exists. Skips weekends, state-specific holidays, employees on approved leave, and employees in Factory departments (their attendance comes from biometric device and must be imported separately).",
				tags: "absent auto mark attendance daily factory biometric skip department",
				note: "Factory employees (any department containing 'Factory') are always excluded. Their attendance must be entered manually or imported via biometric integration.",
			},
			{
				num: "8", title: "Payroll Processing",
				desc: "Two salary structures: IB Payroll (office) and Astro Payroll (factory). PF opt-in via provident_fund_account. ESIC opt-in via health_insurance_no (auto-skipped if base salary exceeds Rs 21,000).",
				tags: "payroll salary pf esic slip process",
				steps: [
					"Ensure each employee has a Salary Structure Assignment.",
					"PF opt-in: set <code>provident_fund_account</code> on the Employee record.",
					"ESIC opt-in: set <code>health_insurance_no</code> on the Employee record.",
					"Run Payroll: HRMS, Process Payroll, select month and company.",
					"Submit all salary slips. Post the payment journal.",
				],
			},
			{
				num: "INC-1", title: "Giving an Employee a Salary Increment",
				desc: "A raise is a new Salary Structure Assignment, not an edit to the Employee record. The Employee form's Cost to Company field is informational only — it does not drive payroll. Salary Slips are calculated from the employee's Salary Structure Assignment.",
				link: "/app/salary-structure-assignment/new", linkLabel: "New Salary Structure Assignment",
				tags: "salary increment raise hike ctc cost to company base structure assignment payroll",
				steps: [
					"Go to <b>Salary Structure Assignment → New</b>.",
					"Select the <b>Employee</b> and the same <b>Salary Structure</b> they're already on (IB Payroll or Astro Payroll).",
					"Enter the new <b>Base</b> amount and set <b>From Date</b> to when the raise takes effect.",
					"Save and Submit. Salary Slips generated for that employee on or after the From Date will use the new Base.",
					"Optional but recommended: update <code>custom_current_ctc</code> (and move the old value into <code>custom_previous_ctc</code>) on the Employee form's IB section — these fields are for record-keeping only, they don't feed payroll.",
				],
				note: "Don't just edit the old Salary Structure Assignment's Base in place — create a new one with a From Date. Keeping the old one intact preserves the correct historical pay rate for any Salary Slip already generated before the raise.",
			},
			{
				num: "33", title: "Full and Final Settlement",
				desc: "IB Full Final Settlement doctype: auto-computes years of service, gratuity (for 5+ years), leave encashment, total payable. Status flow: Draft, In Review, Approved, Paid.",
				link: "/app/ib-full-final-settlement", linkLabel: "F&F Settlement List",
				tags: "fnf final settlement gratuity exit",
			},
			{
				num: "3", title: "Employee Exit and Handover",
				desc: "Set relieving_date on the Employee (status can be Active or Left — either order works). On/after relieving day: Handover doc is created with all pending Quotations, Sales Orders, Delivery Notes, Sales Invoices, and HR Managers get a bell notification. The day after: user account auto-disabled.",
				tags: "exit handover relieve disable account",
			},
			{
				num: "47", title: "State-wise Holiday Lists",
				desc: "Three lists: Maharashtra, Tamil Nadu, Gujarat. Assign to each employee via the holiday_list field. The auto-absent scheduler respects these lists.",
				tags: "holiday state list attendance leave",
			},
			{
				num: "65", title: "Attendance Terminal (Admin Bulk Check-In)",
				desc: "Separate from the employee self-service /checkin portal. The Attendance Terminal page is for HR / Admin to bulk check-in or mark absent for factory and office employees in one operation. Access from Workspace → HR → Attendance Terminal. Privileged users (HR Manager/User, System Manager) can also pick a past or future date via the date picker — non-privileged users are locked to today.",
				link: "/app/attendance-terminal", linkLabel: "Attendance Terminal",
				tags: "attendance terminal bulk check admin factory office absent mark hr not checked in",
				steps: [
					"Go to <b>Workspace → HR → Attendance Terminal</b>.",
					"Filter by category: <b>Factory</b> or <b>Office</b>.",
					"The page shows all employees in that category with their current check-in status: <b>In</b> (green), <b>Out</b> (blue), <b>Done</b> (green, checked in and out), or <b>Not Checked In</b> (gray).",
					"Select employees and click <b>Check In</b> for bulk check-in.",
					"Click <b>Mark Absent</b> to mark selected employees absent (a real Absent Attendance record — genuinely-absent employees don't appear in this list at all once marked).",
					"Late check-in (more than 10 min after shift start) or early check-out (more than 10 min before shift end) auto-triggers a reason dialog.",
					"Reason is saved to <code>custom_late_reason</code> on the Employee Checkin record.",
				],
				tip: "Employees without a default_shift assigned never trigger the late/early reason dialog.",
				note: "<b>Bug fixed 2026-08-22:</b> the status pill previously fell back to a red \"Absent\" label for anyone who simply hadn't checked in yet — including everyone, for a future date, since nobody can check in ahead of time. Confirmed live: 28 of 50 employees showed wrongly \"Absent\" today, and all 55 showed \"Absent\" when viewing tomorrow. Now correctly shows gray \"Not Checked In\" — real Absent records (from Mark Absent or the nightly auto-absent scheduler) are unaffected and still excluded from this list entirely, same as before.",
			},
			{
				num: "32", title: "IB Overtime Request",
				desc: "Employees submit overtime requests via IB Overtime Request (IB-OT-{YYYY}-{#####}). HR Manager approves or rejects. Fields: employee, date, shift, overtime_hours, reason.",
				link: "/app/ib-overtime-request", linkLabel: "Overtime Requests",
				tags: "overtime request employee hr manager approve reject hours shift",
				steps: [
					"Employee goes to <b>IB Overtime Request → New</b>.",
					"System defaults Date = today. Select the Shift.",
					"Enter Overtime Hours (must be greater than 0) and Reason.",
					"Save. Status moves to Pending Approval.",
					"HR Manager reviews: Approve or Reject with Approver Notes.",
					"Status flow: Draft → Pending Approval → Approved / Rejected.",
				],
				note: "Employee role: create and write. HR Manager role: full access including approve/reject. The approved_by and approver_notes fields are read-only for employees.",
			},
			{
				num: "49", title: "Employee Drive Sync",
				desc: "Documents attached to the Employee record (PANCARD, Aadhar, Passport, etc.) are auto-synced to Frappe Drive. The system creates an HR Documents team and a per-employee subfolder. A Drive link button appears on the Employee form.",
				tags: "drive sync employee documents folder team hr pancard aadhar passport",
				steps: [
					"Open the Employee record.",
					"Scroll to the <b>Employee Document</b> table (IB section).",
					"Add rows: select Document Type (PANCARD, AADHAR CARD, Passport, Education Certificate, etc.) and attach the file.",
					"Save. The system enqueues a background job that creates/updates the Drive folder and copies files.",
					"Click the <b>Open in Drive</b> button at the top of the Employee form to open the employee's Drive folder.",
				],
				note: "Drive hierarchy: HR Documents team → Employee Documents → {Name} folder → {Type} - {filename}. If the employee name changes, the Drive folder is renamed automatically. Deleting a child row in ERPNext does NOT delete the file from Drive.",
			},
			{
				num: "OC-1", title: "Org Chart",
				desc: "Interactive org chart showing the reporting hierarchy across all departments and employees. Access from Workspace → HR → Org Chart.",
				link: "/app/ib-org-chart", linkLabel: "Open Org Chart",
				tags: "org chart hierarchy reporting manager employee department structure",
			},
			{
				num: "35", title: "Employee Custom Fields (IB Section)",
				desc: "Custom fields added to the Employee form in the IB section: Emergency Contact, Emergency Phone, Notice Period Days (default 30), Previous Employer, Previous CTC, Current CTC, Location State (Maharashtra / Tamil Nadu / Gujarat). Location State is filterable in the Employee list.",
				tags: "employee custom fields emergency contact notice period previous employer ctc state location",
			},
			{
				num: "MY-HR", title: "My HR — Employee Self-Service Portal",
				desc: "Personal HR portal for each employee. Shows leave balances, recent leave applications, this month's attendance calendar, last 6 payslips, and overtime request history. Access any month's data via the month picker. No admin access needed — each employee sees only their own data.",
				link: "/app/ib-my-hr", linkLabel: "My HR",
				tags: "my hr self service leave balance attendance payslip overtime salary slip month picker personal portal employee",
				steps: [
					"Go to <b>Workspace → HR → My HR</b> (or navigate to /app/ib-my-hr).",
					"<b>Leave Summary:</b> all active leave allocations with used, remaining, and total days per leave type.",
					"<b>Recent Leave Applications:</b> last 30 applications with status (Pending/Approved/Rejected) and date range.",
					"<b>Attendance Calendar:</b> current month's attendance — Present (green), Absent (red), On Leave (blue), Half Day (orange). Use the month picker to view past months.",
					"<b>Payslips:</b> last 6 salary slips with gross, deductions, and net pay. Click any row to open the Salary Slip.",
					"<b>Overtime Requests:</b> recent IB Overtime Request records with status.",
				],
				note: "If no active Employee record is linked to your User account, the page shows an error. Contact HR to link your Employee record.",
			},
			{
				num: "137", title: "Company Asset Loan Register (laptops, tools, phones)",
				desc: "Track company assets checked out to employees — asset code/name/category, who has it, issue date, expected and actual return date, condition notes. A daily alert flags anything overdue.",
				link: "/app/ib-asset-loan", linkLabel: "Asset Loans List",
				tags: "asset loan borrow laptop tool phone equipment checkout return overdue tracker",
				steps: [
					"Go to <b>Workspace, HR, Asset Loans</b> (or <code>/app/ib-asset-loan/new</code>).",
					"Enter <b>Asset Code / Tag</b> and <b>Asset Name</b>, pick a <b>Category</b>, and select the <b>Employee</b> borrowing it.",
					"Set <b>Issue Date</b> (defaults to today) and, if there's a due date, <b>Expected Return Date</b>.",
					"Save. Status starts at <b>Issued</b>.",
					"When the item comes back: open the record, set <b>Actual Return Date</b>, add <b>Condition at Return</b> notes, and save — status flips to <b>Returned</b> automatically.",
				],
				note: "The same asset code can't be Issued to two people at once — return (or mark Lost) the existing loan first. Once a loan is Returned or Lost it's final; create a new loan record rather than trying to reopen it. Employees can see their own loan history but not anyone else's; HR Manager/HR User/System Manager see everything.",
				tip: "Anything past its Expected Return Date is auto-flagged Overdue by the nightly scheduler and bell-notifies HR plus the employee holding it — no need to chase manually.",
			},
		],
	},
	{
		id: "ai", cat: "ai",
		icon: '<iconify-icon icon="lucide:bot" width="17" height="17"></iconify-icon>', color: "#fde8e0", iconColor: "#b85c3a",
		title: "AI Tools",
		roles: _AI,
		items: [
			{
				num: "AI.D1", title: "Document Intake — Turn a Scanned or Pasted Order into a Draft",
				desc: "Upload a photo or scan of a PO/SO (OCR reads it into text automatically) or paste the text directly, AI extracts items/quantities/party, you review the extraction, then convert it into a real draft document once it looks right. Nothing is ever created automatically — a human always confirms the conversion.",
				link: "/app/ib-document-intake", linkLabel: "Document Intake",
				tags: "document intake ai extraction ocr scan photo upload paste text po so email draft convert review matched party",
				steps: [
					"Create a new <b>IB Document Intake</b> record and choose Sales Order or Purchase Order.",
					"Either attach a photo/scan/PDF under <b>Scanned Document</b> and click <b>Run OCR</b> to fill Raw Text automatically, or paste the text into Raw Text yourself.",
					"Click <b>Extract</b> — AI reads Raw Text and fills in item lines, quantities, and tries to match the customer/supplier by name.",
					"Review the extraction. If the party match is ambiguous or not found, pick the right Customer/Supplier yourself — the field is editable exactly for this case.",
					"For a Sales Order intake, also set <b>Location</b> (Maharashtra/Gujarat/Chennai) — required before conversion.",
					"Once everything looks right, click <b>Convert to Draft</b> — creates a real draft SO/PO (never auto-submitted).",
				],
				note: "OCR and AI extraction are two separate steps with separate failure modes. OCR runs locally (Tesseract) and doesn't need any API key — if it can't read the scan it says so under OCR Status / Error and Raw Text stays whatever it was, no guessing. Extraction needs a working Claude API key with credit — if that fails it says so under Extraction Status / Error and the record stays in Draft. Either step can be skipped: type Raw Text directly to skip OCR, or fill in the fields by hand without ever running Extract.",
			},
		],
	},
	{
		id: "broadcast", cat: "comms",
		icon: '<iconify-icon icon="lucide:bell" width="17" height="17"></iconify-icon>', color: "#e0f0ff", iconColor: "#1a60b0",
		title: "Team Chat",
		roles: _SALES,
		items: [
			{
				num: "RAVEN-1", title: "Raven — Internal Team Chat",
				desc: "Raven is the internal team chat app for Instabiz staff. Direct messages, channels, and file sharing between colleagues.",
				link: "/raven", linkLabel: "Open Raven",
				tags: "raven chat internal messaging dm channel team communication",
				steps: [
					"Open Raven from the app switcher (top-left, grid icon) or go directly to <code>/raven</code>.",
					"<b>General channel</b> — every staff member is a member by default; use it for company-wide messages.",
					"<b>Direct Messages</b> — click a colleague's name in the People list to start a 1:1 chat.",
					"<b>New Channel</b> — create a topic or team-specific channel; invite the relevant people.",
					"<b>File sharing</b> — drag and drop or use the attach button inside any conversation.",
				],
				note: "Every enabled user account automatically has Raven access (Raven User role). If someone can't see other people in Raven, it's almost always because they haven't been added to the Raven workspace/General channel yet — contact a System Manager.",
			},
		],
	},
	{
		id: "customerboard", cat: "crm",
		icon: '<iconify-icon icon="lucide:tag" width="17" height="17"></iconify-icon>', color: "#e3f2fd", iconColor: "#1565c0",
		title: "Customer Board and Daily Assignments",
		roles: _SALES,
		items: [
			{
				num: "CB-1", title: "Customer Board (My Board + Team, merged 2026-08-05)",
				desc: "Page: Customer Board (<b>Workspace → Customer Board</b>) — one page, replacing the previously separate Customer Board and Assignment Admin pages/shortcuts.<br><b>My Board tab</b> (every Sales User, Sales Manager, System Manager, Team Leader — everyone with access to the page has their own accounts too): 3 columns — <b>My Accounts</b> (your assigned customer pool, paginated), <b>Today</b> (to contact today, with a progress bar and Completed/Skipped stat cards), <b>Tomorrow</b> (auto-assigned at midnight). Drag a card between columns, or use the Add to Today/Tomorrow pills. Submitting a Sales Order for a customer auto-marks their Today assignment done.<br><b>Team tab</b> (Sales Manager, System Manager, Team Leader only — the tab itself is absent from the tab bar for a plain Sales User, not just hidden): the former Assignment Admin — a roster of every rep grouped by team (avatar, Done/Pending/Tomorrow counts, sales-target progress bar), <b>View As</b> to load and operate any rep's own 4-column board (My Accounts / Regular pool / Today / Tomorrow) on their behalf, team management (add/remove members and states), and incentive-slab configuration.",
				link: "/app/ib-customer-board", linkLabel: "Open Customer Board",
				tags: "customer board kanban my accounts today tomorrow daily plan contact schedule assignment team roster assignment admin view as manager",
				steps: [
					"Go to <b>Workspace → Customer Board</b>.",
					"<b>My Board tab</b> is what everyone sees by default — your own My Accounts / Today / Tomorrow columns.",
					"Click <b>Add to Today</b> or <b>Tomorrow</b> on a My Accounts card to schedule it, or drag the card into the target column.",
					"If you're a Sales Manager, System Manager, or Team Leader, a <b>Team</b> tab appears next to My Board.",
					"On the Team tab, click a rep's <b>⋮ → View board</b> to load and operate their full kanban on their behalf.",
					"Team tab's kebab menu also has Auto-fill, Transfer, and Set Target per rep, plus a team-level ⋮ for Manage Team (members/states).",
				],
				tip: "Your monthly sales target card appears above the My Board columns — shows target amount and MTD revenue so far. The midnight scheduler auto-assigns tomorrow's batch based on your state. Bookmarked URLs look like <code>/app/ib-customer-board</code> (My Board) or <code>/app/ib-customer-board/team</code> (Team) — the Team URL silently falls back to My Board for a non-manager, since the underlying admin RPCs are server-side role-gated independent of which tab you're looking at.",
				note: "Team tab pool pagination: 50 customers per page. Manager actions there are full CRUD — no restrictions on which rep's board is edited.",
			},
			{
				num: "CB-3", title: "IB Assignment Config — Batch Size and Dormant Rules",
				desc: "Singleton doctype that controls how the midnight scheduler builds tomorrow's auto-assigned customer lists: how many customers per rep, how many days without an order = dormant, and what fraction of each day's batch should be dormant customers.",
				link: "/app/ib-assignment-config", linkLabel: "Assignment Config",
				tags: "assignment config batch size dormant threshold days ratio scheduler auto midnight",
				steps: [
					"Search <b>IB Assignment Config</b> in the top bar (System Manager).",
					"Set <b>Assignments Per Day</b>: total customers assigned to each rep per day (e.g. 10).",
					"Set <b>Dormant Threshold Days</b>: days since last SO to classify a customer as Dormant (e.g. 60).",
					"Set <b>Dormant Ratio %</b>: what percentage of each day's batch should be dormant customers (e.g. 30%).",
					"Save. The midnight scheduler uses these values to build tomorrow's auto-assigned lists for all reps.",
				],
				note: "Auto-assignment runs every night at 12 AM. Manually added cards (via Customer Board, including its Team tab) are not affected by the scheduler.",
			},
			{
				num: "CB-4", title: "IB Customer Assignment — Individual Assignment Record",
				desc: "Each assignment is one IB Customer Assignment (ICA-.YYYY.-#####) record: customer, assigned_to (User), assigned_date, status (Pending/Contacted/Order Placed/Skipped/Rolled Over), source_pool (Dormant/Regular), state, outcome.",
				link: "/app/ib-customer-assignment", linkLabel: "Customer Assignment List",
				tags: "customer assignment record pending contacted order placed skipped rolled over status outcome",
				note: "Submitting a Sales Order for a customer on their assignment date auto-updates the assignment status to Order Placed.",
			},
		],
	},
	{
		id: "production", cat: "production",
		icon: '<iconify-icon icon="lucide:factory" width="17" height="17"></iconify-icon>', color: "#fff3e0", iconColor: "#e65100",
		title: "Production Module",
		roles: _PROD,
		items: [
			{
				num: "PROD-0", title: "Production Module — Overview",
				desc: "Tracks raw materials (Jumbo Rolls) through 7 manufacturing stages to finished goods. Links Sales Orders → Order Sheets → Work Orders → Machines → Production Entries. All data flows to the Production Dashboard and DPR report. Roles: System Manager, Factory Management, Sales Manager. Doctypes: IB Work Order, IB Order Sheet, IB Machine, IB Production Entry, IB Jumbo Roll.",
				link: "/app/ib-production-dashboard/stages", linkLabel: "Open Production — Stages tab",
				tags: "production overview manufacturing module doctypes roles work order order sheet machine jumbo roll entry",
			},
			{
				num: "PROD-1", title: "Stage Routing by Location and Item Group — Which Stages Each Product Goes Through",
				updated: "2026-08-13",
				desc: "Not all products go through all 5 stages. Location is checked first: Gujarat is the only factory site, so only Gujarat orders use the item-group routing below. Maharashtra and Chennai are warehouse-only and always route to just Packing. Enforced server-side in _get_stage_route().",
				link: "/app/ib-production-dashboard/stages", linkLabel: "Open Production — Stages tab",
				tags: "stages item group location routing gujarat maharashtra chennai factory warehouse plastic pvc cloth foam aerosol sealant bopp paper reflective skips coating rewinding cutting packing",
				steps: [
					"<b>Location comes first:</b> orders routed to <b>Maharashtra</b> or <b>Chennai</b> always route to just <b>Packing</b> — the item-group rules below never apply there, no matter what the item group is. Only <b>Gujarat</b> orders use the full item-group route.",
					"<b>The item-group rules below only apply to Gujarat orders:</b>",
					"<b>PLASTIC (5 stages):</b> Coating → Slitting → Rewinding → Cutting → Packing.",
					"<b>PAPER / REFLECTIVE (4 stages — no Rewinding):</b> Coating → Slitting → Cutting → Packing.",
					"<b>PVC / CLOTH / FOAM / FOAM - PE / FOIL (3 stages — skip Coating + Rewinding):</b> Slitting → Cutting → Packing.",
					"<b>AEROSOL-* (5 types) / SEALANT-* (2 types) / ADHESIVE-HOTMELT (Packing only):</b> Packing.",
					"<b>Default (unmapped item group, 2 stages):</b> Cutting → Packing.",
					"Packing is the real last stage on every route — nothing is manufactured at \"Ready to Deliver\" or \"Delivered\" anymore (2026-08-13, see the note below and PROD-2).",
				],
				note: "RTD/Delivered were removed from the stage model entirely 2026-08-13 — Packing is the item's true last production stage now. \"Ready to Deliver\" is just what a Completed-through-Packing item IS (Create Delivery Note becomes available); \"Delivered\" is derived from the Delivery Note being submitted, not a stage anyone starts or completes. Stages that don't apply to an item group are simply skipped — no Work Orders are created for them. Also: item_group \"BOPP\" is NOT in the Gujarat routing map despite being a real item_group used elsewhere in the app (e.g. batch tracking) — BOPP items on Gujarat orders silently fall back to the 2-stage default route (Cutting → Packing) rather than a coating/slitting route. Flagged as an unconfirmed gap, not fixed in code — check with Factory Management whether BOPP needs its own route.",
			},
			{
				num: "PROD-2", title: "The 5 Stages — What Each One Does",
				desc: "Each stage = one IB Work Order. Stage colors are consistent across all views: Coating=purple, Slitting=blue, Rewinding=cyan, Cutting=green, Packing=amber.",
				tags: "stages coating slitting rewinding cutting packing fields entry color ready to deliver delivered",
				steps: [
					"<b>1. Coating</b> — Raw Jumbo Roll coated with adhesive. Entry fields: jumbo_roll_width, jumbo_roll_length, coating_speed (m/min), adhesive_consumption (kg).",
					"<b>2. Slitting</b> — Coated roll slit into narrower rolls. Entry fields: no_of_slits, slit_widths (mm, comma-separated), edge_trim_width.",
					"<b>3. Rewinding</b> — Slit rolls rewound onto cores. Entry fields: no_of_logs, log_length, core_size (1/1.5/2/3 inch). Skipped for PVC/CLOTH/FOAM.",
					"<b>4. Cutting</b> — Logs cut to final product length. Entry fields: cut_length, pieces_per_log.",
					"<b>5. Packing</b> — Finished goods packed and QC checked. Entry fields: packing_type (Carton/Shrink Wrap/Poly Bag/Loose), pieces_per_carton, cartons_packed, qc_status (Pass/Fail/Pending). The real last stage on every route (2026-08-13) — completing it is what makes an item production-complete.",
					"<b>\"Ready to Deliver\"</b> is no longer a Work Order — it's what a Completed-through-Packing item IS. Sales person receives a bell notification at 100% production, and Create Delivery Note becomes available.",
					"<b>\"Delivered\"</b> is no longer a Work Order either — it's derived from a Delivery Note actually being submitted against the order (mark_wos_delivered), not a manual step or an auto-advance.",
				],
				updated: "2026-08-13",
			},
			{
				num: "PROD-3", title: "IB Order Sheet — Create and Manage",
				desc: "An Order Sheet = production plan for one Sales Order. Groups all Work Orders for all stages across all items in one view. Must exist before Work Orders can be created for an SO. As of 2026-07-30 you rarely need to create one manually.",
				link: "/app/ib-order-sheet", linkLabel: "IB Order Sheet List",
				tags: "order sheet os create sales order priority delivery date auto scheduler new button start production",
				steps: [
					"<b>Method 1 — Automatic (the normal path):</b> Submitting a Sales Order fires <code>on_so_submit_create_order_sheet</code>, which enqueues a background job that creates the Order Sheet within moments — no button click needed. See PROD-16 for the exact mechanism and priority logic.",
					"<b>Method 2 — Manual, from the Stages tab:</b> Order-wise sub-tab → <b>+ Start Production</b> button (top of the page — the Sales Order form's own production panel is read-only display, it has no create button, see PROD-5a) → select Sales Order, set Priority and Notes, click Create.",
					"After creation: the Order Sheet has zero Work Orders (2026-08-13, JIT stage model — see PROD-4). Nothing is pre-created per stage anymore; a Work Order for an item only exists once someone actually starts that item and picks a stage.",
					"Set <b>Priority</b> (Urgent/High/Normal/Low) and optional <b>Notes</b>. Delivery Date is pulled from the Sales Order, not set here — new Sales Orders now default Delivery Date to 8 days out (see 2.9 in Sales and Quotations).",
				],
				note: "One SO = one Order Sheet. Attempting to create a second Order Sheet for the same SO will show an error. The old nightly-midnight-scheduler path and the old \"+ New Order Sheet\" button name are both gone — see PROD-16.",
				updated: "2026-08-13",
			},
			{
				num: "PROD-4", title: "IB Work Order — Status Lifecycle, Just-In-Time Stage Picker, and Key Fields",
				desc: "A Work Order = one item at one production stage. Status flows: Pending → In Progress → Completed (or On Hold between In Progress and Completed). As of 2026-08-13, Work Orders are created just-in-time — nothing is pre-created for future stages, and there's no auto-advance to a next-stage WO.",
				link: "/app/ib-work-order", linkLabel: "IB Work Order List",
				tags: "work order status lifecycle pending in progress on hold completed fields stage machine operator qty started completed advance next naming start production stage picker jit",
				steps: [
					"<b>Key fields:</b> order_sheet, order_sheet_item, sales_order, item_code, stage, machine, operator, priority, target_qty, completed_qty, wastage_qty, started_at, completed_at, batch_group, pcs_to_make, logs_to_make.",
					"<b>Starting work on an item:</b> click <b>Start Production</b> (Active Production Plan row, or the \"+\" cell on the Order-wise stage grid) — a dialog asks which stage, defaulted to the item's next route stage but freely overridable. Confirming creates exactly one Work Order for that stage, auto-assigns a machine, and puts it straight to In Progress in one step — there's no separate \"create\" then \"start\".",
					"<b>On Hold</b> — Pause mid-stage (machine breakdown, end of shift). Click On Hold. Resume: click Start/Resume again on the same Work Order.",
					"<b>Completed</b> — Click Complete (or Next Stage →, same action, different label depending on whether it's the item's last stage). completed_qty defaults to target_qty since per-stage partial output isn't captured anywhere (IB Production Entry is unused by design — see the FAQ). If another stage remains in the item's route, the same Start Production picker opens immediately, defaulted to the suggested next stage — completing and starting the next bit of work is one continuous flow, not two separate button hunts.",
					"Completing Packing — the real last stage on every route (2026-08-13, see PROD-1/PROD-2) — marks the entire item as production-complete; Create Delivery Note becomes available on the order once every item is done.",
					"Status changes are governed by the IB Work Order Workflow (native ERPNext Workflow builder) — only valid transitions for your role are allowed. Workflow action buttons also appear directly on the raw IB Work Order document if you open one.",
					"There is no manual \"Move to Different Stage\" escape hatch anymore (removed 2026-08-13, same session as the JIT picker) — the Start Production picker is the only way to put a Work Order at any stage, including out-of-sequence or rework corrections (a Completed stage picked again reactivates for rework).",
				],
				note: "WO names follow the plain series <code>IB-WO-{YYYY}-{#####}</code> (e.g. IB-WO-2026-23719) — there is no stage segment in the name itself, the stage is a separate field. WOs can also be viewed in the standard IB Work Order list with filters.",
				updated: "2026-08-13",
			},
			{
				num: "PROD-5", title: "Production Dashboard (Dashboard + Stages, merged 2026-08-05) — All Sections",
				updated: "2026-08-05",
				desc: "Page: Production (<b>Workspace → Production Dashboard</b>) — one page, replacing the previously separate Production Dashboard and Production Stages pages/shortcuts. <b>Dashboard tab</b> (default): real-time factory floor overview — 4 KPI cards, a Location filter, location-scoped pipeline summary, and a searchable/filterable/paginated Active Production Plan table with inline commenting. <b>Stages tab</b>: the former Production Stages — Order-wise (default)/Item-wise/Stage-wise/Machine-wise sub-tabs (Job Bundles removed 2026-08-13, see PROD-12), the Work Order side panel, and machine management. (The old static Priority Strip and Avg Wastage Today cards were removed 2026-07-31 — always showed 0.00%/static counts with no drill-through, judged not useful.)",
				link: "/app/ib-production-dashboard", linkLabel: "Open Production Dashboard",
				tags: "production dashboard kpi active pending completed today machines plan entries pipeline location filter etd search pagination infinite scroll comment hide completed stages tab merged",
				steps: [
					"<b>KPI Card 1 — Active Work Orders</b> (Pending + In Progress). Click → the Stages tab, Item-wise sub-tab, pre-filtered to Pending/In Progress/On Hold — <i>not</i> a raw IB Work Order list (fixed 2026-07-31: it used to route into Order-wise's status filter, which is Order-Sheet-grain and stays \"In Progress\" for an order's whole multi-week run — a grain mismatch against a WO-grain KPI).",
					"<b>KPI Card 2 — Pending.</b> Click → same Item-wise sub-tab, filtered to Pending only.",
					"<b>KPI Card 3 — Completed Today.</b> Click → the DPR report page (its own \"WOs Completed\" KPI is the exact same date-scoped count, computed the same way — a genuine grain+time match, unlike trying to force a live-state tab to show a historical count).",
					"<b>KPI Card 4 — Machines Active</b> (machines with an In Progress WO right now). Click → the Stages tab, Machine-wise sub-tab — <i>not</i> the raw IB Machine list.",
					"<b>Location filter:</b> dropdown — All Locations / Gujarat (Factory) / Maharashtra (Warehouse) / Chennai (Warehouse). Your choice is remembered in your browser (localStorage key <code>ib_prod_location</code>) and shared with the Stages tab automatically. See PROD-6.",
					"<b>Stage Pipeline:</b> 7 stage cards each showing Pending / In Progress / Completed counts + color progress bar. Click any card → the Stages tab, Item-wise sub-tab, filtered to that stage. Only renders once you've picked a specific location (not \"All Locations\") — showing 7 stage cards for a 2-stage warehouse site didn't make sense.",
					"<b>AI Production Actions Panel:</b> pending actions from production agents (prod_advance, prod_machine_assign, prod_notify_ready, prod_auto_os, prod_job_bundle) with Approve/Reject buttons.",
					"<b>Active Production Plan Table:</b> one card per active order, identified by <b>Sales Order only</b> — the underlying Order Sheet record still exists and drives the click-through, but its raw ID is never shown. Each card shows customer, item count and names, current stage, stage-chip progress row, priority, overall progress bar, creation date, and a color-coded <b>ETD</b> badge (green on-track / orange due within 2 days / red overdue) from the SO's Delivery Date.",
					"<b>Search box</b> above the table — filters by Sales Order name or customer name. <b>Priority filter</b> and the page-level <b>Location filter</b> narrow it further.",
					"<b>Hide completed items toggle</b> (default ON) — collapses fully-completed order cards out of the list so the table stays focused on what's actually in flight; switch it off to see everything.",
					"<b>Per-order comment button</b> — posts a real Frappe Comment against the Sales Order (reusing the existing notify_owner_on_comment hook) with a live comment-count badge on the card. Commenting on an order that has active production also fans out a notification to Factory Management/Factory Production/System Manager — a way for sales or management to flag something to the floor without leaving the dashboard.",
					"<b>Pagination:</b> loads 25 order sheets at a time; scrolling down loads more automatically (infinite scroll).",
					"<b>Quick Buttons:</b> Stages tab →, Work Orders →, DPR Report →.",
					"<b>Toolbar:</b> Location filter + Refresh button top-right (Dashboard tab); the Stages tab owns its own toolbar (5 sub-tabs + shared Location filter + Refresh) while active — only one tab's toolbar chrome is shown at a time.",
				],
				note: "<b>PROD-5a — Sales Order form production panel:</b> every submitted Sales Order also shows a small read-only production panel directly on its own form (progress bar, current stage, item-level stage chips, dispatch status) — this is display-only, there's no button on it to create an Order Sheet (see PROD-3). It links out to the full Production Tracker (PROD-25) for sales users.",
			},
			{
				num: "PROD-6", title: "Location Filter — Scoping Production Views by Site (Gujarat / Maharashtra / Chennai)",
				updated: "2026-08-05",
				desc: "Both tabs of the Production page (Dashboard and Stages) share one Location dropdown (All Locations / Gujarat (Factory) / Maharashtra (Warehouse) / Chennai (Warehouse)) that scopes what you see to one site. Replaces the old Kanban/Pipeline tab, which was removed the same day — see the FAQ for why.",
				link: "/app/ib-production-dashboard/stages", linkLabel: "Open Production — Stages tab",
				tags: "location filter gujarat maharashtra chennai factory warehouse site shared localstorage production stages dashboard ib_prod_location",
				steps: [
					"Open the <b>Production</b> page (either tab) and use the <b>Location</b> dropdown in the toolbar.",
					"Options: <b>All Locations</b> (default, no scoping), <b>Gujarat (Factory)</b>, <b>Maharashtra (Warehouse)</b>, <b>Chennai (Warehouse)</b>.",
					"Your selection is saved in your browser (localStorage key <code>ib_prod_location</code>) and automatically applied on the other tab too — pick Gujarat on one, it's already selected on the other.",
					"Gujarat is the only site with a full factory (Coating→Slitting→Rewinding→Cutting→Packing→Ready to Deliver, varies by item group). Maharashtra and Chennai are warehouse-only — any order routed there only ever has Packing → Ready to Deliver, so their production views are intentionally simpler. See PROD-1 for the full routing rules.",
					"On the Dashboard tab, the Stage Pipeline card section only renders once you pick a specific location (see PROD-5) — showing 7 stage cards for a 2-stage warehouse site didn't make sense.",
				],
				note: "The old Pipeline/Kanban tab (drag-and-drop columns) is gone, and so is Job Bundles (removed 2026-08-13, see PROD-12). The Stages tab's own sub-tabs are: Order-wise (default), Item-wise, Stage-wise, Machine-wise. Order-wise is the primary way to see what's happening and start production on an item (see PROD-4). Production Dashboard and Production Stages were two separate pages until 2026-08-05, when they merged into the Dashboard/Stages tabs of this one page — see PROD-5.",
			},
			{
				num: "PROD-7", title: "Work Order Side Panel — All Buttons",
				updated: "2026-08-13",
				desc: "Click any Work Order row in Order-wise, Item-wise, Stage-wise, or Machine-wise to open the right-side detail panel. One contextual primary button (its label changes with WO state) plus a dropdown (▾) for the less-frequent actions.",
				tags: "side panel work order assign machine start resume hold next stage create delivery note buttons panel dropdown order wise machine wise stage wise print job order adjust qty jit start production picker",
				steps: [
					"<b>Panel Header:</b> WO name (monospace), item code, stage chip (colored), priority badge, status chip, machine name, creation date and ETD.",
					"<b>Primary button (exactly one shown, changes with state):</b> <b>Assign Machine</b> (no machine yet — dropdown of Active machines for that stage type, load-balanced suggestion auto-selected) → <b>Start</b> (Pending) → <b>Resume</b> (On Hold — same button id as Start, label swaps) → <b>Next Stage →</b> (In Progress, not the item's last stage — completes the current stage; if another stage remains in the item's route, the Start Production picker opens immediately, defaulted to that suggestion — see PROD-4) → <b>Complete</b> (In Progress, at Packing — the item's real last stage on every route — no next-stage prompt, nothing left to do) → <b>Create Delivery Note</b> (Completed at Packing — scoped to just that single item via <code>custom_make_delivery_note</code>'s <code>item_code</code> param, not the whole Sales Order).",
					"<b>Create Delivery Note gating:</b> only enabled once the whole Order Sheet is Completed (every item, not just this one) — otherwise the panel shows a \"Waiting for other items\" placeholder instead, so a DN can't ship before sibling items on the same order have finished production.",
					"<b>Dropdown (▾) — less-frequent actions:</b> <b>Put On Hold</b> (valid from Pending or In Progress — pauses the WO, e.g. machine breakdown), <b>Adjust Qty</b> (Factory Management/System Manager only — sets <code>pcs_to_make</code>/<code>logs_to_make</code>, manager-set reconciliation values shown on the printed Job Order, separate from target_qty; dialog and panel header show the item's UOM and target qty explicitly, and the wrong field for the WO's UOM is rejected instead of silently accepted). As of 2026-08-13, <b>Print Job Order</b> was removed from this dropdown — <b>IB Job Order Summary</b> (see PROD-26) is the only print format actually used for Production.",
				],
				note: "Panel is 440px wide. Closes with Esc. Completing a Work Order auto-refreshes the tab you're viewing, and — if another stage remains — opens the Start Production picker automatically (see PROD-4). <b>There is no manual \"Move to Different Stage\" button anymore</b> (removed 2026-08-13, same session as the JIT stage picker) — the Start Production picker is now the only way to put a Work Order at any stage, including out-of-sequence corrections or rework (picking an already-Completed stage reactivates it). <b>\"+ New Entry\" / Entries History were removed from this panel 2026-08-05</b> — see PROD-8, that feature never had real data behind it. The old <b>Link Jumbo Roll</b> button (Coating/Slitting WOs) was removed 2026-07-31 — confirmed confusing and never actually used (0 real links ever); backend function still exists, dormant. Jumbo Roll batch lineage is tracked via the Item-wise tab (PROD-9) and IB Jumbo Roll doctype directly (PROD-13).",
			},
			{
				num: "PROD-8", title: "Logging a Production Entry — Removed 2026-08-05 (never had real data)",
				updated: "2026-08-05",
				desc: "This used to describe a \"+ New Entry\" dialog on the Work Order side panel for logging shift-level input/output/wastage per WO. <b>Removed from the panel 2026-08-05</b> (see PROD-7) after confirming <code>IB Production Entry</code> has zero rows system-wide, always has — nothing in the real completion flow (Start/Next Stage/Complete) ever wrote to it. Every downstream report that read from it (DPR — PROD-15, IB Production Report) was permanently empty and has since been rebuilt to read real <code>IB Work Order</code> completion data instead.",
				tags: "production entry log new entry dialog removed dead wastage reason stage fields submit history",
				note: "Not deleted — the backend dialog code (<code>_show_entry_dialog()</code>) and the <code>IB Production Entry</code> doctype still exist, dormant, same precedent as the earlier Seat Map/Link Jumbo Roll removals. Wastage tracking (<code>wastage_qty</code>/<code>wastage_pct</code>) is hardcoded 0.0 on every real Work Order and never written anywhere else — there is currently no real wastage-capture flow in the app at all (see PROD-11, PROD-15).",
			},
			{
				num: "PROD-9", title: "Item-wise Tab — Per-Item Stage Progress and Batch Lineage",
				updated: "2026-08-03",
				desc: "The Stages tab's Item-wise sub-tab. Each item card shows all active stages, completion %, linked Jumbo Rolls. Click for stage table and batch lineage traceability. Also the target of the Dashboard tab's Active/Pending/Stage-Pipeline KPI cards (see PROD-5) since this sub-tab is genuinely Work-Order-grain and spans every order.",
				tags: "item wise tab item code stages active completion jumbo roll batch lineage link search status filter route options",
				steps: [
					"Click the <b>Item-wise</b> tab.",
					"<b>Item cards:</b> item_code (bold), item name, active stage chips (color-coded), overall completion %, Jumbo Roll pills.",
					"<b>Search:</b> type in the search box to filter by item code.",
					"Arriving here via a Dashboard KPI card auto-applies a <code>status</code> filter (e.g. Pending, or any-of Pending/In Progress/On Hold) — clear it from the filter bar to see everything again.",
					"<b>Click a card</b> to expand detail:",
					"  → <b>Stage Progress table:</b> each stage with chip, WO name, status, assigned machine, progress bar.",
					"  → <b>Batch Lineage section:</b> shows JR batch_no → which WOs consumed it → output chain, for any roll already linked via IB Jumbo Roll (see PROD-13 — the old in-panel Link Jumbo Roll button was removed 2026-07-31, linking now happens by setting the field directly on the Jumbo Roll or WO record).",
				],
				tip: "Use batch lineage to trace quality issues back to specific raw material batches.",
			},
			{
				num: "PROD-10", title: "Order-wise Tab — Order Sheet List and Stage Matrix",
				updated: "2026-08-03",
				desc: "The Stages tab's Order-wise sub-tab — the default sub-tab. Lists all Order Sheets with filters and search. Click into one for three detail subtabs.",
				tags: "order wise tab sheet list filter status priority subtab matrix product stage machine create wo start production default search location filter print job order summary",
				steps: [
					"Click the <b>Order-wise</b> tab (or just land here — it's the default).",
					"<b>Filters:</b> Status (All / Draft / In Progress / Completed), Priority (All / Urgent / High / Normal / Low), plus the page-level <b>Location</b> filter (All Locations / Gujarat / Maharashtra / Chennai — see PROD-6).",
					"<b>Search box:</b> filters the table by Sales Order name or customer name.",
					"<b>Table columns:</b> Sales Order, Customer, Items count, Progress bar, Priority badge, Status, View button, and a <b>Print</b> (printer icon) button — the raw Order Sheet ID isn't shown as a column; the Order Sheet record still exists underneath and drives the click-through.",
					"<b>Print button</b> — prints the <b>IB Job Order Summary</b> format: one landscape page listing every item's FULL stage×machine×operator grid (see PROD-26). Works for orders at any completion level, including 100% done (fixed 2026-08-11).",
					"<b>+ Start Production button</b> — opens dialog: Sales Order (link), Priority, Notes. Creates Order Sheet and auto-generates the full WO chain (route depends on location — see PROD-1). See PROD-3.",
					"<b>Click View / a row</b> → Order Sheet detail with 3 subtabs:",
					"  → <b>Order-wise subtab:</b> items list with their Work Orders per stage, shown as compact stage-pill chips (CT/SL/RW/CU/PK/RTD/DL, colored by status) plus a progress bar — full detail on hover, click opens the side panel (PROD-7). Each row is keyed by the item's own <code>order_sheet_item</code> record, not by item_code alone, so two rows sharing the same item code on one order never cross-contaminate each other's Work Order list (fixed 2026-07-31).",
					"  → <b>Product-wise subtab:</b> stage matrix — rows = items, columns = 7 stages. Icons: ✓ (Completed, green), ▶ animated (In Progress, blue), ⏱ (Pending, grey), + (no WO exists — click to create one instantly).",
					"  → <b>Machine-wise subtab:</b> machine cards showing all WOs from this Order Sheet assigned to each machine.",
				],
				note: "Clicking + in the Product-wise matrix directly creates a WO for that item at that stage without any dialog.",
			},
			{
				num: "PROD-11", title: "Machine-wise Tab — Machine Load and Stats",
				updated: "2026-08-03",
				desc: "The Stages tab's Machine-wise sub-tab. All active machines with live load, today's real output/wastage/yield, and WO list. Create and edit machines from here.",
				tags: "machine wise tab load output wastage yield capacity edit create new machine card entries today stats quality control despatch",
				steps: [
					"Click the <b>Machine-wise</b> tab.",
					"<b>Machine card shows:</b> machine code (bold), machine type (color badge: Coating=purple, Slitting=blue, Rewinding=cyan, Cutting=green, Packing=amber; Quality Control and Despatch machine types also exist), location badge, load % bar.",
					"<b>Today stats:</b> real Output, Wastage %, and Yield % (100 − wastage), sourced directly from IB Work Order records completed today on that machine — not from IB Production Entry, which has zero rows ever (see the FAQ). Wastage/Yield read 0%/100% for every machine until a real wastage-capture flow exists, since nothing currently writes <code>wastage_pct</code> on a WO outside its 0.0 default — this is a data-capture gap, not a display bug.",
					"<b>Load % color:</b> each machine handles 1 Work Order at a time; load = count of In-Progress WOs × 100%, capped at 200% display. Green 0%, red once 2+ WOs are In Progress simultaneously on one machine (a real overload signal, not a formula bug) — this is independent of the machine's own <code>capacity</code> field.",
					"<b>WO list on card:</b> active WOs assigned to this machine with status chips, creation date, and ETD.",
					"<b>Edit button:</b> change capacity, capacity_uom, wastage norm, location, status.",
					"<b>+ New Machine button</b> (top right): machine_code, machine_name, machine_type (Coating / Slitting / Rewinding / Cutting / Packing / Quality Control / Despatch), location (maharashtra / gujarat / chennai), capacity, capacity_uom (exact Select options: <code>sqm/hour</code>, <code>rolls/hour</code>, <code>pcs/hour</code>, <code>kg/hour</code>, <code>ctn/shift</code>), wastage_norm_pct, status (exact Select options: <code>Active</code>, <code>Inactive</code>, <code>Under Maintenance</code>).",
				],
				note: "Machine type must match stage — only Coating machines appear in the Coating WO Assign Machine picker. \"Despatch\" and \"Quality Control\" are valid machine_type Select options but currently unused — no stage maps to either since RTD/Delivered were removed from the stage model (2026-08-13, see PROD-1/PROD-2).",
			},
			{
				num: "PROD-12", title: "Running Several Same-Item Orders on One Machine",
				desc: "The Stages tab's sub-tabs are Order-wise (default), Item-wise, Stage-wise, and Machine-wise. Starting Production always assigns a machine and starts the Work Order in the same step — there's no separate batch-assignment step.",
				tags: "job bundles tab batch assign machine pending work orders same item stage group",
				steps: [
					"Start each order via the Start Production picker (PROD-4).",
					"Pick the same machine each time when Assign Machine offers a choice — this puts all of them on that machine's run.",
				],
			},
			{
				num: "PROD-13", title: "IB Jumbo Roll — Raw Material Traceability",
				updated: "2026-08-03",
				desc: "Each incoming raw material roll is logged as an IB Jumbo Roll. Can be linked to Coating/Slitting WOs for full batch lineage. Tracks which raw roll produced which finished goods.",
				link: "/app/ib-jumbo-roll", linkLabel: "IB Jumbo Roll List",
				tags: "jumbo roll raw material batch traceability link coating slitting in stock in production consumed status batch no gsm width length liner",
				steps: [
					"Create <b>IB Jumbo Roll</b> when material arrives: supplier, received_date, batch_no, GSM, width_mm, length_mtr, liner_type. Status = In Stock.",
					"Linking a roll to a Coating/Slitting Work Order is done directly on the records (IB Jumbo Roll or IB Work Order) — the in-panel <b>Link Jumbo Roll</b> button that used to live in the WO side panel and Item-wise tab was removed 2026-07-31 (confusing, never actually used — 0 real links ever existed through it). The backend linking function still exists, dormant.",
					"In Item-wise tab: click an item card → Batch Lineage section shows the full chain for any roll that has been linked: JR batch_no → WOs → finished items (see PROD-9).",
				],
				note: "A roll cannot be linked to two active Work Orders simultaneously (enforced server-side with an advisory lock). Only Coating and Slitting stages participate in lineage — other stages inherit it from upstream.",
			},
			{
				num: "PROD-14", title: "IB Machine — Setup and Configuration",
				updated: "2026-08-03",
				desc: "Machines must be created before they can be assigned to Work Orders. Machine Type determines which stage's picker they appear in. Status controls visibility.",
				link: "/app/ib-machine", linkLabel: "IB Machine List",
				tags: "machine setup configuration new machine type location capacity uom wastage norm active inactive under maintenance quality control despatch",
				steps: [
					"Go to <b>Machine-wise tab → + New Machine</b> or <b>IB Machine List → New</b>.",
					"<b>machine_code:</b> short identifier (CTG-01, SLT-02, RWD-01, CUT-03, PKG-01).",
					"<b>machine_name:</b> full descriptive name.",
					"<b>machine_type</b> (exact Select options): <code>Coating</code>, <code>Slitting</code>, <code>Rewinding</code>, <code>Cutting</code>, <code>Packing</code>, <code>Quality Control</code>, <code>Despatch</code>. Must match the stage — Ready to Deliver and Delivered both map to Despatch; Quality Control is a valid option but no stage currently routes to it.",
					"<b>location:</b> maharashtra / gujarat / chennai.",
					"<b>capacity + capacity_uom</b> (exact Select options): <code>sqm/hour</code>, <code>rolls/hour</code>, <code>pcs/hour</code>, <code>kg/hour</code>, <code>ctn/shift</code>.",
					"<b>wastage_norm_pct:</b> acceptable wastage baseline. Entries above this show red / ABOVE NORM in DPR and Machine-wise.",
					"<b>status</b> (exact Select options): <code>Active</code> (appears in assignment pickers), <code>Inactive</code> (hidden), <code>Under Maintenance</code> (orange badge in Machine-wise tab).",
				],
				note: "capacity/capacity_uom are stored and displayed but not currently used in the Machine-wise load % calculation — see PROD-11 for how load % is actually computed.",
			},
			{
				num: "PROD-15", title: "DPR — Daily Production Report (Daily and Weekly Views)",
				updated: "2026-08-05",
				desc: "Workspace → Production → DPR Report. Date-based report of real production output. Two modes: Daily (one date, stage breakdown) and Weekly (7-day trend). <b>Rebuilt 2026-08-05</b> to read <code>IB Work Order</code> completions directly — the original version read <code>IB Production Entry</code>, which has zero rows system-wide, so it had shown an empty stage breakdown since inception regardless of real floor activity.",
				link: "/app/ib-dpr", linkLabel: "Open DPR",
				tags: "dpr daily weekly production report kpi stage breakdown machine output hours shift hourly avg",
				steps: [
					"Go to <b>Workspace → Production → DPR Report</b>.",
					"<b>Toolbar:</b> Date picker (defaults today), Daily/Weekly toggle buttons, Refresh button.",
					"<b>Daily mode — 3 KPI cards:</b> WOs Completed, Total Output, Total Hours (from real <code>started_at</code>/<code>completed_at</code> timestamps).",
					"<b>Stage Breakdown table:</b> Stage, WOs Completed, Output Qty, Hours, Hourly Avg — one row per stage that had a completion that day.",
					"<b>Click a stage row</b> to expand its machine-level subtable: Machine, WOs Completed, Output.",
					"<b>Weekly mode — 2 KPI cards:</b> Total Output (Week), Avg Daily Output.",
					"<b>Daily Breakdown table (weekly):</b> Date, WOs Completed, Output (with proportional bar), Hours.",
				],
				note: "<b>Wastage is intentionally absent from this report, not just zeroed</b> — <code>IB Work Order.wastage_qty</code>/<code>wastage_pct</code> are hardcoded 0.0 at creation and never written by any real completion path (Production Entry, the only place that ever set them, has zero rows — see PROD-8). Showing \"0% wastage\" would read as measured quality control that was never actually captured, so the efficiency bar and ABOVE NORM badges were removed along with the dead data path rather than left showing a fake zero. Same fix applied to the <b>IB Production Report</b> Script Report (Workspace → Production → Production Report), which was 100% built on Production Entry and had the identical always-empty problem.",
				tip: "Use Daily mode for shift handover reviews. Use Weekly mode for manager-level production trend reviews.",
			},
			{
				num: "PROD-16", title: "Auto Order Sheet Creation — Fires on SO Submit",
				desc: "Order Sheets are auto-created the moment a Sales Order is submitted, not on a nightly delay. Priority set automatically based on delivery date urgency.",
				tags: "auto order sheet on submit immediate priority urgent high normal low delivery date automatic create scheduler",
				steps: [
					"Changed 2026-07-21: previously a midnight scheduler (run_daily_production_snapshot) scanned for SOs without an Order Sheet once a day, bounded to a rolling 30-day window. That job has been removed — there is no longer a nightly scheduler for this.",
					"Now: Sales Order on_submit fires instabiz.overrides.production.on_so_submit_create_order_sheet, which enqueues a background job (after commit — doesn't slow down or risk the SO submit itself) that creates the Order Sheet within moments of submission.",
					"Sets priority by days until delivery_date from the SO:",
					"  → ≤ 2 days: <b>Urgent</b>",
					"  → ≤ 5 days: <b>High</b>",
					"  → ≤ 10 days: <b>Normal</b>",
					"  → > 10 days (or no delivery date): <b>Low</b>",
					"WOs are auto-created per stage per item based on item group routing, further scoped by location as of 2026-07-31 — Gujarat gets the full item-group route, Maharashtra/Chennai always get just Packing → Ready to Deliver. See PROD-1.",
				],
				note: "No more 30-day backlog gap for NEW SOs going forward — every submitted SO gets an Order Sheet within moments, always, regardless of how old the deployment is. Manual creation from the SO or Order-wise tab still exists as a fallback (e.g. if the background job errors — check Error Log for 'Production Auto-Create (on-submit)'). Pre-existing old SOs that predate this change and never got an Order Sheet are NOT retroactively picked up by this — that's a one-time backfill question, not something this trigger solves.",
			},
			{
				num: "PROD-17", title: "RTD Bell Notification to Sales Person",
				desc: "When all items in an Order Sheet reach Ready to Deliver stage, a bell notification is automatically sent to the Sales Person assigned to that Sales Order.",
				tags: "rtd ready to deliver bell notification sales person order sheet all items completed automatic",
				steps: [
					"Production marks the last Packing WO as Complete.",
					"System advances WO to Ready to Deliver stage.",
					"Instabiz checks: are all items in this Order Sheet at RTD or later?",
					"If yes: Frappe bell notification sent to the linked SO's sales person (user).",
					"Notification message: '<customer> order ready to deliver' with link to the Order Sheet.",
					"Sales person sees the bell icon light up in the toolbar.",
				],
				note: "Notification sends only once per Order Sheet — when the last item crosses RTD. Handled by on_work_order_update_notify() in production.py.",
			},
			{
				num: "PROD-18", title: "SO List Production Badges",
				desc: "The Sales Order list view shows a production status badge for each SO that has an Order Sheet. Updates in real time as Work Orders advance.",
				tags: "so sales order list production badge status not started in production ready to deliver dispatched in transit delivered",
				steps: [
					"Open <b>Sales Order list</b> from any workspace.",
					"Each SO row shows a colored production badge (if an Order Sheet exists):",
					"  → <b>Not Started</b> (grey) — Order Sheet created, no WOs started.",
					"  → <b>In Production</b> (blue) — at least one WO In Progress.",
					"  → <b>Ready to Deliver</b> (orange) — all items at RTD stage.",
					"  → <b>Dispatched</b> (purple) — Delivery Note submitted against this SO.",
					"  → <b>In Transit</b> (teal) — DN submitted with shipping tracking.",
					"  → <b>Delivered</b> (green) — DN delivered/closed.",
				],
			},
			{
				num: "PROD-20", title: "Work Order Status — Native Workflow Builder (n8n removed 2026-07-30)",
				desc: "n8n was fully removed — PM2 process stopped, n8n_hooks.py deleted, webhook config gone. Work Order status transitions (Start/Resume/Complete/Hold/Cancel) now run through a native Frappe Workflow instead of an external webhook integration.",
				tags: "n8n removed workflow builder work order status transition start complete hold resume cancel automation production",
				steps: [
					"Go to <b>Workflow List</b> (search-bar → \"Workflow\") → <b>IB Work Order Workflow</b> to see the full state/transition map, or open any IB Work Order doc directly — native workflow action buttons appear top-right.",
					"States: Pending → In Progress → Completed, with On Hold reachable from Pending or In Progress, and Cancel reachable from Pending/In Progress/On Hold.",
					"Each transition is role-gated to Factory Management, Factory Production, or System Manager — same roles as before, just enforced by the Workflow engine instead of a hand-rolled permission check.",
					"The existing Stages-tab Order-wise / Machine-wise buttons still work exactly as before — they call the same whitelisted methods (start_work_order, complete_work_order, put_on_hold, advance_to_next_stage), which now apply the workflow transition internally instead of writing the status field directly.",
					"Bell notifications (25/50/75/100% progress to the sales person, On Hold alerts) are unchanged — they fire from the same IB Work Order.on_update hook, which now fires reliably on every transition since it's a real doc.save() under the hood.",
				],
				note: "If you need cross-system automation again in future (e.g. calling out to a courier API on dispatch), prefer Frappe's own Server Script / Webhook doctypes over reviving n8n — no separate process to keep alive.",
			},
			{
				num: "PROD-21", title: "End-to-End Production Workflow",
				updated: "2026-08-13",
				desc: "Complete step-by-step from Sales Order to dispatch through the full production system. Rewritten for the Just-In-Time stage model (2026-08-13) — Work Orders are no longer pre-created per stage; each one is created only when someone actually starts it and picks a stage.",
				tags: "end to end workflow complete so order sheet work order dispatch full cycle jit start production",
				steps: [
					"<b>1.</b> Sales team submits Sales Order.",
					"<b>2.</b> Order Sheet is auto-created within moments (background job on SO submit — see PROD-16); no manual step needed. If it errors or you need to short-circuit it, create manually via Production Stages → Order-wise → <b>+ Start Production</b> (see PROD-3).",
					"<b>3.</b> Order Sheet created with zero Work Orders — nothing is pre-assigned or pre-routed yet (see PROD-4).",
					"<b>4.</b> Open <b>Production Stages → Order-wise</b> (default tab). Use the Location filter to scope to one site (see PROD-6).",
					"<b>5.</b> Click <b>Start Production</b> on the item (Active Production Plan row, or the \"+\" cell on the Order-wise stage grid). Pick the stage in the dialog (defaults to the item's first route stage) — this creates the Work Order, auto-assigns a machine, and starts it, all in one step.",
					"<b>6.</b> Click <b>Next Stage →</b> once that stage is physically done — completes it and, if more stages remain in the item's route, immediately opens the Start Production picker again for the next one.",
					"<b>7.</b> Repeat step 6 for each subsequent stage. Packing is the real last stage on every route — completing it there uses <b>Complete</b> instead (no further prompt).",
					"<b>8.</b> Once every item on the order has completed Packing → the Order Sheet flips to Completed. Bell notification sent to sales person at 100% (also at 25/50/75% milestones along the way — see PROD-25). Create Delivery Note becomes available.",
					"<b>9.</b> Print a floor copy any time via the WO side panel's <b>Print</b> button (IB Job Order) or the Order-wise row's Print button (IB Job Order Summary) — see PROD-26.",
					"<b>10.</b> Sales creates Delivery Note from the SO. Production badge on SO → Ready to Deliver → Dispatched → Delivered (Delivered is now derived purely from the Delivery Note being submitted, not a Work Order stage).",
					"<b>11.</b> End-of-day: review <b>DPR</b> (Daily mode) for output and hours per stage and machine.",
				],
			},
			{
				num: "PROD-25", title: "Production Tracker — Sales-Facing Order Progress (New)",
				desc: "Workspace → Production Tracker. Lets Sales User/Manager see exactly where each of their Sales Orders sits in the production pipeline without asking the factory floor — progress %, current stage, delivery-risk color coding, and a click-through per-item stage timeline. Pagination, priority/stage filters, sortable columns, CSV export.",
				link: "/app/ib-production-tracker", linkLabel: "Open Production Tracker",
				tags: "production tracker sales facing progress stage timeline milestone notification risk overdue on hold sales order",
				steps: [
					"Go to <b>Workspace → Production Tracker</b> (Sales User, Sales Manager, System Manager).",
					"Each row = one in-flight Sales Order: progress bar, current stage/bottleneck, delivery-risk color (green on-track / amber at-risk / red overdue).",
					"Click a row to open the per-item stage timeline for that order.",
					"Use the filter bar to narrow by priority or stage, or the search box to find an order/customer; sortable columns; Export to CSV.",
					"You get a bell notification automatically at 25%, 50%, 75%, and 100% (Ready to Deliver) production progress for your own orders — no need to keep refreshing the tracker.",
					"If an order gets paused On Hold on the factory floor, you get a bell for that too — previously silent.",
				],
				note: "Same overall progress/risk view is also embedded directly on the Sales Order form (production panel) with a cross-link to the full tracker. Before this feature (added 2026-07-27), Sales had zero visibility into production stage/progress — only a single notification at 100% complete.",
			},
			{
				num: "PROD-26", title: "Job Order Printing — Floor-Worker Print Formats (New, 2026-07-31)",
				updated: "2026-08-03",
				desc: "Two dedicated print formats give the factory floor a paper document with zero customer/Sales Order information on it — just what a machine operator needs (item, dimensions, qty, machine, signature line).",
				tags: "job order print format printing pdf floor worker signature pieces logs to make adjust qty stage workflow summary landscape",
				steps: [
					"<b>IB Job Order</b> (doctype IB Work Order, its default_print_format) — one full page per Work Order: item code/name/stage/machine, dimensions (joined from the matching Sales Order Item row by item_code — the customer/SO name itself is never shown), qty + UOM, conditional Pieces-to-Make/Logs-to-Make (see Adjust Qty below), Jumbo Roll size, signature footer. As of 2026-08-13, the WO side panel's dropdown no longer has a Print Job Order button (removed — <b>IB Job Order Summary</b> below is the one format actually used); this format is still the WO doctype's default_print_format, so it's still reachable via the WO document's own native Print button if ever needed.",
					"<b>IB Job Order Summary</b> (doctype IB Order Sheet, its default_print_format, landscape) — a single compact page per order listing every item's FULL stage×machine×operator grid (done/current/pending/not-in-route all visually distinct — every stage shown, not just the current one). Print from the Order-wise tab's <b>Print</b> (printer icon) button (see PROD-10). As of 2026-08-11: also works correctly for a fully-Completed order (previously showed \"No active Work Orders to print\" and refused to print at all once every item finished — a real bug, since a finished order's paper trail is exactly when you'd want the full summary; the pre-flight check was looking at the wrong signal). Completed stage cells now also show the operator's name (blank for older Work Orders that predate the operator field being set).",
					"<b>Adjust Qty dialog</b> — Factory Management/System Manager only, from the WO side panel. Sets <code>pcs_to_make</code>/<code>logs_to_make</code> (Int, shown per target_uom on the printed Job Order) — manager-set reconciliation values for wastage/efficiency tracking, separate from and blank until explicitly set (unlike target_qty, which is always populated from the Sales Order). As of 2026-08-10: dialog explicitly states \"Item UOM: X — target qty Y\" (previously only implied via the field label), the WO panel header always shows Target qty+UOM, and the backend now rejects setting <code>logs_to_make</code> on a PCS-target WO (or vice versa) instead of silently storing it.",
				],
				note: "Both formats are Jinja custom_format=1 print formats — their doctype-level margin_top/left/right/bottom fields are dead/no-op in that mode; page margins are actually controlled by a <code>.print-format{margin:0mm}</code> CSS rule instead (a genuinely obscure Frappe quirk, worth knowing if you ever need to adjust these formats).",
			},
			{
				num: "PROD-27", title: "Manual Stage Move — Any Stage, Not Just the Item's Route (2026-08-05)",
				desc: "The stage-picker in the WO side panel (icon toggle next to Start/Next Stage) lets a production user manually move an item to any of the 7 canonical stages at that order's location — it is no longer limited to the item's usual item-group route.",
				tags: "move work order stage manual picker escape hatch route override coating slitting rewinding cutting packing",
				steps: [
					"Open the WO side panel (Order-wise or Item-wise tab) and click the move icon next to Start/Next Stage.",
					"Pick any stage from the dropdown and confirm — this works even if that stage isn't normally part of this item's production route (e.g. sending a PVC item to Coating for a one-off need).",
					"If the target stage has no existing Work Order for this item, one is created on the fly; if the target stage's WO was already Completed (e.g. moving Ready-to-Deliver back to Packing for rework), it's reopened to Pending.",
					"Location is still enforced: Gujarat can reach all 7 stages, but Maharashtra/Chennai (warehouse-only, no factory machines physically there) are still limited to Packing → Ready to Deliver.",
				],
				note: "Between 2026-07-31 and 2026-08-05 this was restricted to only the stages in the item's own item-group route (to stop phantom Work Orders on warehouse-only orders) — loosened back at production users' request, since moving stage-to-stage is routine work for that role, not just an out-of-sequence correction. See CLAUDE.md item 120.",
			},
			{
				num: "PROD-28", title: "IB Production Recipe + MRP — Raw Material Planning (New, 2026-08-10)",
				updated: "2026-08-10",
				desc: "IB Production Recipe records how much of each raw material a finished item needs. Once recipes are entered, MRP runs daily: explodes open Sales Order demand through those recipes, checks raw-material stock, and auto-creates a draft Material Request for any shortfall.",
				link: "/app/ib-production-recipe", linkLabel: "Production Recipe List",
				tags: "production recipe mrp material requirement planning raw material shortfall draft material request bom",
				steps: [
					"Set up a recipe: <b>IB Production Recipe</b>, one row per finished item → raw material → qty needed per unit of the finished item.",
					"MRP runs automatically every day — no manual step needed once recipes exist.",
					"If a raw material is short for open order demand, a <b>draft Material Request</b> appears automatically — review and submit it as normal.",
					"Re-runs are safe: an existing draft covering the same shortfall isn't duplicated.",
				],
				note: "This app doesn't use native ERPNext Manufacturing (BOM/Work Order/Job Card) — IB Production Recipe is this app's own lightweight equivalent, built for this need specifically. Without any recipes entered, MRP has nothing to explode and does nothing.",
			},
			{
				num: "PROD-29", title: "Production Twin — Delivery Feasibility Check (New, 2026-08-10)",
				updated: "2026-08-10",
				desc: "Before promising a delivery date, run a what-if check: given a Sales Order (or an ad-hoc item list) and a target delivery date, this simulates the real current Work Order backlog, machine capacity, and raw-material availability to estimate whether the factory can actually deliver by that date. Read-only — it never creates or changes any real record.",
				tags: "production twin simulate feasibility delivery date what if backlog machine capacity material availability",
				steps: [
					"Available to Factory Management / System Manager via the whitelisted simulate check.",
					"Give it a Sales Order (or a list of items) and a target delivery date.",
					"It weighs current Work Order backlog, machine load, and — once recipes exist (see PROD-28) — raw material availability.",
					"Returns a feasibility read so you can set expectations with Sales before committing to a date.",
				],
				note: "Like MRP, the material-availability portion of this check is only as good as the IB Production Recipe data behind it — with no recipes entered, that part of the check has nothing to work with.",
			},
			{
				num: "PROD-30", title: "Creating a Delivery Note Straight from Production (New, 2026-08-11)",
				updated: "2026-08-11",
				desc: "Once every item on an order has reached Completed at every stage, a Create Delivery Note button appears directly in Production — no need to go find the Sales Order and use its own Create menu.",
				tags: "create delivery note production order wise item wise active production plan dispatch ready",
				steps: [
					"<b>Order-wise → Order-wise</b> (Stages page): button appears in the order header once ready — creates one Delivery Note covering every item on the order.",
					"<b>Item-wise</b> detail view: same whole-order button appears next to the item name once the order it belongs to is ready.",
					"<b>Active Production Plan</b> (Dashboard tab): once every item in an order card is done, an inline Create Delivery Note button appears right where the card's item table would normally be.",
					"<b>Work Order side panel</b> (any tab): the existing per-item Create Delivery Note button, unchanged — creates a Delivery Note scoped to just that one item, useful for shipping one item before the rest of the order catches up (this is the only one of the four that doesn't require the whole order to be done).",
				],
				note: "Submitting that Delivery Note automatically moves the item's Work Order to the Delivered stage — see PROD-2, item 7.",
			},
			{
				num: "PROD-31", title: "Floors — Factory Floor Management (New, 2026-08-27)",
				desc: "A Floor Management master for Gujarat (the only current factory) — reuses the real Warehouse tree that already exists there (Ground/First/Second Floor - GUJARAT - IB) rather than inventing a separate hierarchy. Each floor record says which of the 5 production stages (Coating/Slitting/Rewinding/Cutting/Packing) that physical floor is actually equipped for. Machines can then be assigned to a specific floor, and Production's auto machine-assignment will only pick a machine for a stage its floor actually supports — a Cutting job will never land on a machine sitting on a Coating-only floor.",
				link: "/app/ib-production-floor", linkLabel: "Open Floors",
				tags: "floor floors production floor management warehouse sub-warehouse factory expansion machine assignment stage capability ground first second",
				steps: [
					"<b>Instabiz Production workspace → Floors</b>.",
					"New record: pick the <b>Warehouse (Floor)</b> — must be a real leaf warehouse under MAHARASHTRA - IB / GUJARAT - IB / CHENNAI - IB, not a location grouping. Location is derived automatically.",
					"Tick which stages that floor is equipped for under <b>Allowed Stages</b>.",
					"On <b>Machines</b> (Edit Machine dialog), set the new <b>Floor</b> field once a floor record exists for it — optional, blank keeps the old location-only behavior.",
				],
				note: "Additive by design — Sales Order's own Location field and everything downstream of it (GST, e-way bill, naming) is completely untouched. A machine with no Floor set keeps working exactly as before; only machines you explicitly assign a Floor to get stage-restricted. Scoped to Gujarat for now — Maharashtra/Chennai stay warehouse-only until one of them gets real factory floors of its own.",
			},
			{
				num: "PROD-32", title: "Bulk Start Production — Several Lines at Once (New, 2026-08-30)",
				desc: "One SKU sold as several separate line items at different dimensions (width/color/etc) is common — clicking Start Production once per row was slow. A checkbox now appears next to Start Production on the Active Production Plan (Dashboard tab); tick several and a Bulk Start button appears in the toolbar. The dialog shows one grid — a row per ticked line, a column per stage — each row pre-checked with that item's own next stage, since two ticked items can genuinely be at different points even though both show the same button (adjust any row individually before starting). For lines that haven't had their one-time packing-details form filled in yet, fill it in once in the same dialog and it's applied to every line that needs it. Every (item, stage) pair still goes through the exact same single-item start path under the hood, one at a time, so nothing about how a Work Order actually gets created changes.",
				link: "/app/ib-production-dashboard", linkLabel: "Open Production",
				tags: "bulk start production multiple lines same sku dimension variant checkbox mass start batch per item stage grid",
				steps: [
					"Active Production Plan (Dashboard tab): tick the checkbox next to any row still showing Start Production.",
					"Toolbar's Bulk Start (N) button appears — click it.",
					"Each ticked item's row comes pre-checked with its own suggested next stage — tick/untick any cell to change what starts on that specific item.",
					"If any ticked line hasn't captured packing details yet, fill in Brand/Core/CTN/etc once — applied to every line missing it; a line that already has its own is left untouched. Leave blank to skip those lines instead (start them individually to fill this in there).",
					"Results show how many started / were skipped / failed, then the plan refreshes.",
				],
				note: "Delivery Note now shows it too: if production's Adjust Qty reconciliation (Work Order side panel → ⋯ → Adjust Qty) ever differs from the originally planned quantity, the Delivery Note created from that order carries a Qty Adjustment note on the line (e.g. \"Packing: 100 → 95 PCS\") — informational only, the delivered qty itself is unchanged.",
			},
		],
	},
	{
		id: "banking", cat: "finance",
		icon: '<iconify-icon icon="lucide:landmark" width="17" height="17"></iconify-icon>', color: "#e8f5e9", iconColor: "#1a7f37",
		title: "Finance and Banking",
		roles: _FINANCE,
		items: [
			{
				num: "79", title: "Bank Statement Import",
				desc: "Workspace, Finance, Bank Import. Upload HDFC NetBanking CSV. Preview rows, then import to create Bank Transaction records (Unreconciled). It's actually a 3-stage chain: Import → match in the native Bank Reconciliation Tool → check clearance status in the IB Bank Reconciliation report (see item 75 below) — the result screen links to both (2026-08-05).",
				link: "/app/ib-bank-statement-import", linkLabel: "Bank Import",
				tags: "bank statement import hdfc csv reconcile",
				updated: "2026-08-05",
				steps: [
					"Download HDFC CSV from NetBanking portal.",
					"Go to <b>Workspace, Finance, Bank Import</b>.",
					"Drag-and-drop or upload the CSV file.",
					"Preview parsed rows with deposit and withdrawal summary.",
					"Click Import. Duplicate rows are auto-skipped.",
					"On the result screen, click <b>Open Bank Reconciliation Tool →</b> to match transactions to Payment Entries, or <b>View Reconciliation Status →</b> to jump straight to the IB Bank Reconciliation report.",
				],
			},
			{
				num: "75", title: "IB Bank Reconciliation Report",
				desc: "Reports, IB Bank Reconciliation. Payment Entries for IB bank accounts with clearance status (Cleared / Uncleared). Shows entries pending 7+ days. Toolbar has two shortcut buttons (added 2026-08-05): <b>Match Transactions →</b> (native Bank Reconciliation Tool) and <b>Import More →</b> (back to Bank Statement Import) — a Script Report, not a custom page, so it keeps its native filter bar/chart/export while still cross-linking the other two stages of the chain.",
				link: "/app/query-report/IB Bank Reconciliation", linkLabel: "View Report",
				tags: "bank reconciliation report cleared uncleared match transactions import more",
				updated: "2026-08-05",
			},
			{
				num: "74", title: "Bank Accounts",
				desc: "Two HDFC accounts: GUJARAT and MAHARASHTRA (A/c 50200023672503, IFSC HDFC0000627) and CHENNAI (A/c 50200044619421). Default is the MH and GJ account.",
				tags: "bank account hdfc ifsc account number",
			},
			{
				num: "59", title: "IB AP Aging Report",
				desc: "Outstanding Purchase Invoices bucketed into 0-30, 31-60, 61-90, 90+ days overdue. Bar chart. Summary cards: count, unique suppliers, total payable, 90+ value. Filter by supplier.",
				link: "/app/query-report/IB AP Aging", linkLabel: "View Report",
				tags: "ap aging purchase invoice outstanding payable supplier overdue",
				note: "Use alongside IB AR Aging for a complete picture of receivables vs payables. 90+ bucket is color-coded red.",
			},
			{
				num: "COL-1", title: "Collections Dashboard",
				desc: "Live outstanding receivables dashboard for Sales and Accounts teams. Shows per-customer summary: outstanding amount, advance payments, net outstanding, oldest invoice, and last 90-day collection trend. Filter by sales rep, search by customer name, or toggle Overdue Only. Privileged users (Sales Manager, Accounts) see all reps; Sales User sees only their own customers.",
				link: "/app/ib-collections-dashboard", linkLabel: "Collections Dashboard",
				tags: "collections dashboard outstanding receivables advance overdue customer rep filter search 90 days",
				steps: [
					"Go to <b>Workspace → Finance → Collections Dashboard</b> (or navigate to /app/ib-collections-dashboard).",
					"Default view: all outstanding invoices for your customers. Toggle <b>Overdue Only</b> to show only invoices past due date.",
					"<b>Search</b> by customer name or invoice number.",
					"<b>Sales Managers and Accounts users</b>: use the Rep filter dropdown to view any rep's portfolio.",
					"Each customer row shows: invoice count, outstanding, advance (unallocated payment), net outstanding, oldest due date.",
					"Click a customer row to expand the invoice drill-down (all unpaid invoices for that customer with days overdue).",
					"KPI cards at top: Total Outstanding, Total Advance, Net Outstanding, Customer Count, Overdue Count, Collected Last 90 Days.",
				],
				note: "Advance shown = unallocated Payment Entries (Receive type, party=Customer). Net Outstanding = Outstanding − Advance.",
			},
		],
	},
	{
		id: "targets", cat: "sales",
		icon: '<iconify-icon icon="lucide:trophy" width="17" height="17"></iconify-icon>', color: "#fff8e0", iconColor: "#b8860b",
		title: "Sales Targets and Performance Monitoring",
		roles: _MANAGERS,
		items: [
			{
				num: "14", title: "Setting Monthly Sales Targets",
				updated: "2026-07-25",
				desc: "Sales Managers create a monthly revenue target per rep using IB Sales Target (IB-ST-.YYYY.-#####). The rep sees their target card on the Customer Board. Scheduler sends bell alerts at 50% and 75% month elapsed if behind pace, and at month-end if target not met.",
				link: "/app/ib-sales-target", linkLabel: "Sales Targets",
				tags: "sales target monthly revenue rep user manager set bell alert pace",
				steps: [
					"Go to <b>IB Sales Target → New</b> (Sales Manager or System Manager only).",
					"Select <b>Sales User</b> and <b>Month</b> (system normalizes to first of month).",
					"Enter <b>Target Amount</b> (currency).",
					"Save. One target per user per month — duplicates are rejected.",
					"The rep's Customer Board page shows a target card with progress for the current month.",
					"Customer Board's Team tab roster shows a sales target bar per user.",
				],
				note: "Sales User can read their own target but cannot create or edit it. Sales Manager and above can create and edit all targets. <b>Basis (2026-07-25):</b> \"Actual\" on the target card counts submitted <b>Sales Orders</b>, not Sales Invoices — billing isn't live yet. It's counted by the date the order was <b>entered into the system</b> (creation), not the date printed on the order (transaction date) — this matches the Sales Order list view's own default date filter, so the two always agree. A backdated or late-entered order counts toward the month it was typed in.",
			},
			{
				num: "15", title: "Customer Health Score",
				desc: "Daily scheduler auto-computes a 0–100 health score per active customer: payment punctuality (35%), order frequency (30%), complaint count (20%), CSAT rating (15%). Status: Green ≥70, Amber ≥40, Red <40. If a customer's score drops 15+ points, all Sales Managers get an email alert.",
				link: "/app/ib-customer-score", linkLabel: "Customer Score List",
				tags: "customer health score green amber red payment frequency complaint csat drop alert email daily",
				steps: [
					"Score is computed automatically every night — no manual action needed.",
					"View scores via <b>Workspace → Sales & CRM → Customer Health</b>.",
					"Each IB Customer Score record stores: score_date, health_status, total_score, previous_score, score_change, and component scores.",
					"If score drops 15+ points in a day, an email is sent to all Sales Manager and System Manager users.",
				],
				tip: "Use Customer Health to prioritize outreach. Red = at risk of churn. Amber = needs attention. Green = healthy.",
			},
			{
				num: "13", title: "Dormant Customer Detection",
				desc: "Daily scheduler: customers with no submitted Sales Order in 60+ days get a ToDo assigned to their sales rep, plus a bell notification for quick follow-up. One alert per customer (deduplicated via [ib-dormant-reminder] marker in the ToDo description).",
				tags: "dormant customer 60 days no order alert todo re-engage",
				note: "The dormant threshold matches IB Assignment Config's dormant_threshold_days setting.",
			},
			{
				num: "21", title: "Fulfillment SLA Alert (48-Hour)",
				desc: "Daily scheduler: submitted Sales Orders with no linked submitted Delivery Note after 48 hours trigger a bell notification to the assigned sales rep. Ensures timely dispatch. One alert per SO (deduplicated via [ib-sla-alert] marker in the Notification Log subject).",
				tags: "fulfillment sla alert 48h dispatch delivery note no dn overdue",
				note: "Alert fires once per SO and is not repeated daily. Once a DN is submitted against the SO, future runs skip it.",
			},
			{
				num: "22b", title: "Win-Back Nudges for Stale Opportunities",
				desc: "Daily scheduler sends win-back alerts for: (1) Open/Replied Quotations with no activity in 14+ days → alert to the sales rep. (2) Leads in Cold, Contacted, or Warm status with no activity in 30+ days → alert to lead_owner. Re-alerts every 14 days as long as the document stays stale.",
				tags: "win back nudge stale quotation lead cold warm contacted no activity dormant alert bell repeat",
				note: "Activity measured by last modified timestamp. Alerts repeat every 14 days — if a quotation stays Open for a month, the rep gets two nudges. Win-back and dormant customer alerts are separate.",
			},
		],
	},
	{
		id: "dashboards", cat: "dashboard",
		icon: '<iconify-icon icon="lucide:layout-dashboard" width="17" height="17"></iconify-icon>', color: "#fef6f2", iconColor: "#d97757",
		title: "Dashboards",
		roles: ["Sales Manager", "Accounts User", "System Manager", "Purchase Manager", "HR Manager"],
		items: [
			{
				num: "DASH-1", title: "Main Dashboard (Business Pulse)",
				desc: "Top-level business overview: Revenue MTD, Outstanding AR, Open Quotations, Low/Zero Stock count. Revenue Trend 6-month chart. Top Customers bar chart. Recent Invoices table. All KPI cards are clickable deep-links.",
				link: "/app/ib-main-dashboard", linkLabel: "Open Dashboard",
				tags: "main dashboard business pulse revenue ar quotation stock kpi trend top customers invoices",
				steps: [
					"Go to <b>Workspace → Dashboards → Dashboard</b> (Business Pulse).",
					"4 KPI cards: <b>Revenue MTD</b> (→ SI list), <b>Outstanding AR</b> (→ unpaid SI list), <b>Open Quotations</b> (→ Quotation list), <b>Low/Zero Stock</b> (→ Stock Dashboard).",
					"Revenue Trend chart shows 6-month monthly revenue (bar chart).",
					"Top Customers bar shows top 10 by monthly order value.",
					"Recent Invoices table shows last 10 submitted SIs with status badges.",
					"Click any KPI card to open the filtered document list.",
				],
				tip: "Best used as a morning quick-check for Sales Managers and System Managers.",
			},
			{
				num: "DASH-2", title: "Finance Dashboard",
				desc: "6 KPI cards: Revenue MTD, Gross Profit MTD, Outstanding AR, Cash & Bank, Expenses MTD, Revenue YTD. P&L trend chart. Top Vendors bar. GST Summary. Cash/Bank Balances. Overdue Receivables table.",
				link: "/app/ib-finance-dashboard", linkLabel: "Finance Dashboard",
				tags: "finance dashboard revenue gross profit ar ap cash gst overdue receivables vendors expense ytd",
				steps: [
					"Go to <b>Workspace → Dashboards → Finance Dashboard</b>.",
					"6 KPI cards: Revenue MTD (→ SI list), Gross Profit MTD (→ Gross Margin report), Outstanding AR (→ unpaid SI list), Cash & Bank (→ Bank Account list), Expenses MTD (→ PI list), Revenue YTD (→ SI list).",
					"P&L trend chart (6-month). Top Vendors bar chart.",
					"GST Summary section shows current month GST liability estimate.",
					"Cash/Bank Balances section shows HDFC MH+GJ and Chennai balances.",
					"Overdue Receivables table: SIs past due date with outstanding amount.",
				],
			},
			{
				num: "DASH-3", title: "HR Dashboard",
				desc: "4 KPI cards: Active Employees, Present Today, Pending Leaves, Payroll MTD. Tabs: Attendance, Leaves, Payroll, Statutory. Approve/reject leaves inline. Department headcount bars.",
				link: "/app/ib-hrms-dashboard", linkLabel: "HR Dashboard",
				tags: "hr dashboard employees attendance leaves payroll statutory approve reject department headcount",
				steps: [
					"Go to <b>Workspace → Dashboards → HR Dashboard</b>.",
					"4 KPI cards: <b>Active Employees</b> (→ Employee list), <b>Present Today</b> (→ today's Attendance list), <b>Pending Leaves</b> (→ Leave Application list), <b>Payroll MTD</b> (→ Salary Slip list).",
					"<b>Attendance tab</b>: Department headcount bars. Today's present/absent/late count by shift.",
					"<b>Leaves tab</b>: Pending Leave Applications with inline Approve / Reject buttons.",
					"<b>Payroll tab</b>: Salary slip status this month (Draft/Submitted count).",
					"<b>Statutory tab</b>: PF, ESIC, PT deduction totals for current payroll month.",
				],
				tip: "Use the Leaves tab for quick leave approvals without opening each Leave Application individually.",
				note: "<b>Bug fixed 2026-08-22:</b> the Attendance tab's list previously only read submitted `Attendance` records — which only ever get a \"Present\" row from HRMS's own end-of-day auto-attendance job, never live during the day — so today's real check-ins never showed up as Present in the list (only Absent records, created via Attendance Terminal's Mark Absent or the nightly scheduler, ever appeared for today). The \"Present Today\" KPI card above it was always correct (computed live from Employee Checkin) — the list just disagreed with it. Fixed by merging in a live \"Present\" row for anyone checked in today with no Attendance doc yet, so the list and the KPI can no longer disagree.",
			},
			{
				num: "DASH-4", title: "Procurement Dashboard",
				desc: "5 KPI cards: Open POs, Pending GRN, Spend MTD, Overdue AP, Draft Bills. All deep-linked to filtered document lists. Top Suppliers bar chart. Recent POs table.",
				link: "/app/ib-procurement-dashboard", linkLabel: "Procurement Dashboard",
				tags: "procurement dashboard po grn spend ap bills suppliers overdue draft receipt",
				steps: [
					"Go to <b>Workspace → Dashboards → Procurement Dashboard</b>.",
					"5 KPI cards: <b>Open POs</b> (→ submitted PO list), <b>Pending GRN</b> (→ submitted GRN list), <b>Spend MTD</b> (→ submitted PI list), <b>Overdue AP</b> (→ overdue PI list), <b>Draft Bills</b> (→ draft PI list).",
					"Top Suppliers bar chart shows top 10 by MTD spend.",
					"Recent POs table lists last 10 submitted POs with receipt + billing status.",
					"Click any KPI card to drill into the filtered document list.",
				],
			},
			{
				num: "DASH-5", title: "Production Dashboard KPIs and Deep Links",
				updated: "2026-07-31",
				desc: "4 KPI cards: Active WOs, Pending WOs, Completed Today, Machines Active. All clickable deep-links. A Location filter scopes the stage pipeline, which only shows once a location is picked. Priority strip, wastage card, searchable/paginated active plan table with ETD badges.",
				link: "/app/ib-production-dashboard", linkLabel: "Production Dashboard",
				tags: "production dashboard wo stage kpi machines active pending completed wastage priority plan order sheet location filter etd",
				steps: [
					"Go to <b>Workspace → Production → Production Dashboard</b>.",
					"4 KPI cards: <b>Active WOs</b> (→ IB Work Order list In Progress), <b>Pending</b> (→ Pending WOs), <b>Completed Today</b> (→ WOs completed today), <b>Machines Active</b> (→ IB Machine list Active).",
					"Pick a <b>Location</b> from the new filter to see the stage pipeline (Coating→Slitting→Rewinding→Cutting→Packing→RTD→Delivered) — it stays hidden on \"All Locations\" now, since a mixed view across a 6-stage factory and 2-stage warehouses didn't make sense. Click any stage card → the Stages tab. See PROD-5/PROD-6 for full detail.",
					"Priority strip shows Urgent/High/Normal/Low WO counts.",
					"Wastage card shows today's average wastage %.",
					"Active Plan table lists all active orders by Sales Order (no raw Order Sheet ID shown), with a search box and infinite-scroll pagination (25 at a time), plus a color-coded ETD badge per card.",
				],
			},
			{
				num: "DASH-6", title: "Analytics Hub — content-aware by role",
				desc: "8 tabs — Sales, Inventory, Production, HR, Finance, Procurement, Docs, Me — each showing KPIs + a trend chart + a breakdown. Every tab is open to every role from any of the 6 role-specific workspaces; what you see inside each tab depends on your role, not which tabs you can click.",
				link: "/app/ib-analytics-hub", linkLabel: "Analytics Hub",
				tags: "analytics hub cross module sales inventory production hr finance procurement docs me content aware scoped role purchase stock order chain outstanding search filter",
				steps: [
					"Shortcut lives in all 6 workspaces now, not just Instabiz (Sales): <b>Instabiz</b> (Dashboards), <b>Instabiz Production</b> (Production section), <b>Instabiz HR</b> (Dashboards), <b>Instabiz Finance</b> (Dashboards), <b>Instabiz Stock</b> (Inventory), <b>Instabiz Procurement</b> (Dashboards) — each role sees it from their own workspace, no permission error.",
					"Every tab is open to every role. Which tab gives you the full company-wide view vs. your own scoped view depends on whether the tab is <i>your</i> domain:",
					"<b>Sales</b> tab — privileged: System Manager, Sales Manager. Everyone else sees their own orders/customers only.",
					"<b>Inventory</b> tab — privileged: System Manager, Sales Manager, Accounts Manager, Factory Management, Stock Manager. Everyone else sees in-stock / out-of-stock status only per item — no real quantities or stock value.",
					"<b>Production</b> tab — privileged: System Manager, Sales Manager, Accounts Manager, Factory Management. Everyone else sees their own Sales Orders' current production stage and dispatch status (same data as the Production Tracker page).",
					"<b>HR</b> tab — privileged: System Manager, HR Manager, HR User (plus the base Sales/Accounts/Factory managers). Everyone else sees their own leave balance, this period's attendance, pending leave requests, last payslip — not company headcount or payroll.",
					"<b>Finance</b> tab — privileged: System Manager, Sales Manager, Accounts Manager, Accounts User, Factory Management, Purchase Manager. Everyone else sees their own customers' outstanding AR and collections only — no AP, no other reps' customers.",
					"<b>Procurement</b> tab (new) — privileged: System Manager, Accounts Manager, Purchase Manager, Purchase User, Factory Management — spend, open POs, pending GRNs, outstanding AP, spend by vendor. Everyone else sees open PO / pending GRN counts only — no spend figures.",
					"<b>Docs</b> tab — for Sales/Accounts/System Manager roles, one row per Sales Order showing its whole journey in one place: Quotation → Order → Dispatch → Invoice → Payment → Production stage → Outstanding, so you can see exactly what's still pending on any order without checking 4 different screens. Sales User sees only their own orders; Sales Manager/Accounts/System Manager see everyone's, plus a <b>Sales Person filter</b> to narrow the company-wide view to one rep. Each chain badge that has a real document behind it (Quoted, Dispatched, Invoiced) is a clickable link straight to that Quotation/Delivery Note/Sales Invoice — badges with nothing behind them yet (Not Created / Not Dispatched) stay plain text so they never look like a dead link. For HR User/HR Manager this tab shows a different view instead — a combined list of pending Leave/Overtime/Full &amp; Final Settlement/Salary Slip requests across the company. Has a search box, status filter chips, and pages through 10 at a time.",
					"<b>Me</b> tab — unchanged, always self-scoped for everyone regardless of role.",
					"Daily / Weekly / Monthly period selector and the CSV export both work the same regardless of which view (scoped or company-wide) you're looking at. (Procurement and Docs don't use the period selector — Docs is always current state, Procurement KPIs are current-period totals.)",
				],
				tip: "If a number looks unexpectedly small on Sales/Inventory/Production/HR/Finance/Procurement, check whether that tab is your role's domain — a non-privileged-for-that-tab user is intentionally only seeing their own work, not a bug. Stock User and Purchase User (non-Manager, except on their own Procurement tab) are deliberately left scoped everywhere, same as any other operational role. On the Docs tab, an order showing \"Outstanding\" with no invoice yet is normal right now — billing isn't live, so it's the order value minus any advance received, not a real invoice balance.",
			},
		],
	},
	{
		id: "followups", cat: "dashboard",
		icon: '<iconify-icon icon="lucide:calendar-check" width="17" height="17"></iconify-icon>', color: "#e0f2fe", iconColor: "#0369a1",
		title: "Follow-Ups",
		roles: _ALL,
		items: [
			{
				num: "137", title: "Follow-Ups — Cross-Department Follow-up Tool",
				desc: "Workspace → Follow-Ups (every workspace has this shortcut). A single page, open to every role, for logging follow-ups against your own documents across Sales, Purchase, and HR — generalizes the same Type/Outcome/Notes/Next-Date pattern Lead's \"Log Activity\" already uses, but works on Quotation, Sales Order, Delivery Note, Sales Invoice, Purchase Order, Purchase Receipt, Purchase Invoice, Leave Application, IB Overtime Request, IB Full Final Settlement, and Employee Exit Handover. Pick a document type, see your own documents (owned, assigned to you, or — for sales docs — your rep field; for HR docs — matched via your linked Employee record) with a status chip (Pending / Followed Up / Overdue), click one to log a follow-up. Already-decided documents (a Quotation already converted to an Order, a Cancelled/Closed document, an already-Approved/Rejected HR request) are left off the list entirely — nothing to chase there. Overdue documents always sort to the top. Summary cards and filter chips (All / Pending / Overdue / Followed Up) narrow the list; a phone/WhatsApp icon appears next to any row with a contact number on file. Logging a follow-up also posts a note on the actual document's own timeline, same as Lead's activity log.",
				link: "/app/ib-follow-ups", linkLabel: "Open Follow-Ups",
				tags: "follow up followup follow-up dashboard log activity call meeting outcome next date overdue pending track history past logged",
				steps: [
					"Go to <b>Workspace → Follow-Ups</b> (any workspace — it's the same page everywhere).",
					"Pick a <b>Document Type</b> from the dropdown.",
					"Your own documents for that type list below, each with a status chip — use the filter chips or search to narrow down.",
					"Click <b>Log Follow-up</b> on a row — the dialog opens showing every follow-up already logged against that document (type, outcome, notes, who, when) before the form to log a new one.",
					"Pick Type + Outcome, add Notes, optionally set a Next Follow-up Date → Save.",
					"The list and the summary cards refresh immediately.",
				],
				note: "You can only ever log a follow-up against a document that's actually yours (owner, assigned via Assign To, or the doctype's own rep/employee field) — enforced server-side regardless of what the page shows, not just a UI restriction. There is no company-wide/manager view in this version — every user only ever sees their own documents.",
			},
		],
	},
	{
		id: "faq", cat: "faq",
		icon: '<iconify-icon icon="lucide:help-circle" width="17" height="17"></iconify-icon>', color: "#f3e8ff", iconColor: "#7c3aed",
		title: "Frequently Asked Questions",
		roles: _ALL,
		items: [
			{
				num: "FAQ-1", title: "Why was I marked Absent even though I clocked in?",
				desc: "Two different root causes, both fixed 2026-07-15 — but check which one applies to you.",
				tags: "faq absent attendance clocked in punched default shift checkin factory office sales wrong",
				steps: [
					"<b>Office/Sales staff:</b> if your Employee record had no <code>default_shift</code> set, your real terminal punches couldn't be matched to a shift, so HRMS never converted them to a Present record — the nightly auto-absent job then marked you Absent despite clocking in. Backfilled for the affected employees; the auto-absent job was also hardened to never mark anyone Absent if a real check-in exists that day, regardless of shift matching.",
					"<b>Factory staff:</b> a separate issue — nobody has been feeding real punches into either capture path (Attendance Terminal or Biometric Import) for Factory department, so HRMS's own Factory Shift auto-attendance job was marking everyone Absent by default with zero real data behind it. That auto-marking has been switched off; Factory attendance now stays blank instead of wrong until Attendance Terminal or Biometric Import is actually used daily (see FAQ-10).",
				],
				note: "If you're still seeing wrong Absent records from before 2026-07-15, those historical records were not automatically corrected — ask HR to review, since fixing them touches payroll-adjacent submitted documents.",
			},
			{
				num: "FAQ-2", title: "Where did the Seat Map / Live Floor tabs in Production Stages (now the Stages tab) go?",
				desc: "Both were built and then removed the same day at the requester's own follow-up request.",
				tags: "faq seat map live floor removed missing tab gone production stages",
				steps: [
					"Seat Map showed cutting/slitting machine width occupancy as a movie-seat-style grid.",
					"Live Floor showed real-time occupancy across all 7 stages.",
					"Both were reviewed and explicitly removed from the page.",
				],
			},
			{
				num: "FAQ-3", title: "Whatever happened to n8n?",
				desc: "Removed entirely 2026-07-30 — it was tested, mostly failed (90%+ historical error rate), and sat unused. Work Order status automation now runs on a native Frappe Workflow instead (see PROD-20).",
				tags: "faq n8n removed automation workflow builder",
				steps: [
					"No process to check, no config to set — the Workflow-based replacement is part of the app itself, no external service to keep running.",
					"If something that used to depend on n8n seems to have stopped, it didn't lose functionality — the same Start/Complete/Hold/Cancel actions on IB Work Order work the same as before, just through the native Workflow engine.",
				],
			},
			{
				num: "FAQ-4", title: "Why don't I see a shortcut I expect in my workspace?",
				desc: "Most workspace shortcuts are restricted to specific roles (restrict_to_role) so people only see what they can actually act on.",
				tags: "faq missing shortcut workspace role permission not visible",
				steps: [
					"If you have read-only access to something, the shortcut may be intentionally hidden from your role to keep the workspace uncluttered — ask a manager/System Manager to check via the doctype's Role Permissions Manager.",
					"If you believe you should have edit access and don't, that's a permission request, not a bug — raise it with System Manager.",
				],
			},
			{
				num: "FAQ-5", title: "How does a new Sales Order automatically become production work?",
				updated: "2026-08-03",
				desc: "Submitting the Sales Order itself triggers it — not a nightly job. See PROD-16 for the full mechanism.",
				tags: "faq new sales order automatic production job scheduler on submit immediate",
				steps: [
					"You don't have to do anything — submitting the SO fires a background job that creates the Order Sheet (+ full Work Order chain) within moments.",
					"This changed 2026-07-21 from an old nightly-midnight scan to an on-submit trigger — if you're thinking of the old \"runs at midnight\" behavior, that's no longer how it works.",
					"If it doesn't appear within a minute or two, check the Error Log for \"Production Auto-Create (on-submit)\", or create it manually from the Stages tab → Order-wise → <b>+ Start Production</b> (see PROD-3).",
				],
			},
			{
				num: "FAQ-6", title: "Why can't I find the Debit Note shortcut in the Finance workspace anymore?",
				updated: "2026-08-03",
				desc: "It moved. Debit Note (and the rest of the purchase-side shortcuts) relocated to the dedicated Instabiz Procurement workspace in the 2026-07-24 workspace split — it was never really Finance-team work.",
				tags: "faq debit note accounts user permission not working procurement workspace moved",
				steps: [
					"Instabiz Procurement (Purchase User, Purchase Manager, System Manager) is where Debit Note, Purchase Order/Receipt/Invoice, AP Aging, and Purchase Pipeline live now.",
					"Accounts User/Accounts Manager are not in that workspace's role list, so if you're on the Accounts side you won't see it there — that's expected, not a bug.",
				],
			},
			{
				num: "FAQ-7", title: "The Instabiz CRM workspace I used to see is gone",
				desc: "That was an undocumented duplicate of the native ERPNext CRM workspace (renamed but never properly hidden) — it duplicated Lead/Quotation/Sales Order/Customer/Opportunity shortcuts already covered better by the main Instabiz workspace. Hidden intentionally 2026-07-15.",
				tags: "faq crm workspace missing gone duplicate hidden",
			},
			{
				num: "FAQ-8", title: "Why does Customer Outstanding Amount / AR Aging / AP Aging now show real numbers based on Sales/Purchase Orders instead of Invoices?",
				desc: "Real invoicing (Sales/Purchase Invoice) isn't live in the ERP yet, so every AR/AP figure, Collections Report/Dashboard, Customer Health, Sales Incentives, and Purchase Pipeline reads Sales Order / Purchase Order amounts instead, minus any advance already paid — a deliberate testing-phase stand-in, not a bug.",
				tags: "faq outstanding amount zero ar aging ap aging dev prod billing mode toggle sales order purchase order testing",
				steps: [
					"Controlled by one central switch: <code>instabiz.overrides.billing_mode</code> (site config key <code>ib_billing_mode</code>, currently <code>dev</code>).",
					"In <b>dev</b> mode: every AR/AP/outstanding figure across the app is computed from submitted Sales Orders / Purchase Orders (minus advance paid), so reports show real data even though few real invoices exist yet.",
					"Once real Sales/Purchase Invoicing goes live, flipping the config key to <code>prod</code> switches every one of these reports back to genuine Invoice-based figures — a one-line config change, no code changes needed.",
				],
				note: "Not yet switched: overdue_alert.py (7/15/30-day overdue reminders + the 30-day new-order block) still reads Sales Invoice, since flipping it has real behavioral consequences — it can block new Sales Order submission for a customer. Needs its own sign-off before switching, unlike the read-only reports/dashboards above.",
			},
			{
				num: "FAQ-9", title: "Sales Incentives is blank when I open it — is that broken?",
				desc: "No — as of 2026-07-29 the page never calculates automatically. Managers must pick a sales person (or \"All Sales Reps\") from the dropdown first; Sales Users see their own number load automatically with no picker. See SALES-28 for the full calculation breakdown.",
				tags: "faq sales incentives blank empty not loading dropdown select",
			},
			{
				num: "FAQ-10", title: "Why don't I see a Pipeline/Kanban tab or Job Bundles in the Stages tab anymore?",
				updated: "2026-08-13",
				desc: "Pipeline/Kanban removed 2026-07-31 (drag-and-drop was confusing); Job Bundles removed 2026-08-13 (see PROD-12 — its candidate pool can't exist anymore under the JIT stage model). The Stages tab's sub-tabs are now Order-wise (default), Item-wise, Stage-wise, Machine-wise.",
				tags: "faq pipeline kanban job bundles removed missing tab production stages drag drop gone",
				steps: [
					"Order-wise is the primary way to see what's happening and start production on an item now (see PROD-4).",
					"Everything the Pipeline tab could do (start/hold/complete a stage) is still available — click a Work Order row in Order-wise, Item-wise, Stage-wise, or Machine-wise to open the same side panel, which has Next Stage →, Assign Machine, and Create Delivery Note. There's no manual stage-move button anymore — the Start Production picker (PROD-4) is the only way to put a Work Order at any stage now.",
					"A new shared Location filter (Gujarat/Maharashtra/Chennai) replaces some of what the old Pipeline columns were used for — see PROD-6.",
				],
				note: "See PROD-7 for the full list of side panel buttons.",
			},
			{
				num: "FAQ-11", title: "Why does my Maharashtra/Chennai order only have 2 stages (Packing → Ready to Deliver)?",
				updated: "2026-07-31",
				desc: "By design, as of 2026-07-31 — Gujarat is the only factory location. Maharashtra and Chennai are warehouse-only, so any order routed there always gets just Packing → Ready to Deliver, regardless of item group.",
				tags: "faq maharashtra chennai two stages packing ready to deliver warehouse only gujarat factory location routing",
				note: "See PROD-1 for the full location + item-group routing rules, and PROD-6 for the Location filter that lets you view production scoped to one site at a time.",
			},
		],
	},
];

const KB_WORKFLOWS = {
	lead: {
		title: "Lead / Customer — Starting the Sales Process",
		body: `
<p>Start with a <b>Lead</b> (prospect) or an existing <b>Customer</b>.</p>
<ul class="ib-kb-steps">
  <li>Create Lead: CRM, Lead, New. Enter name, mobile, email, state.</li>
  <li>Enter Pincode — city and district auto-fill from India Post API.</li>
  <li>Lead is auto-assigned to a sales rep via round-robin (based on state).</li>
  <li>Log activities: Call, Meeting, WhatsApp, Email, Visit with outcome and next follow-up date.</li>
  <li>When ready: Lead, Make, Customer (custom mapper carries state, pincode, sales person).</li>
</ul>
<div class="ib-kb-tip">Lead Score (0-100) is auto-computed from temperature, status, and contact completeness. Leads with score above 30 and product interest set get AI auto-quote suggestions.</div>`,
	},
	quotation: {
		title: "Quotation — Sending a Price Quote",
		body: `
<ul class="ib-kb-steps">
  <li>Go to Quotation, New. Set Location (Maharashtra / Gujarat / Chennai).</li>
  <li>Select Quotation To: Customer or Lead.</li>
  <li>Add items with dimensions. Qty auto-calculates from width x length x qty_pkg x total_pkg.</li>
  <li>Rate auto-applies from Pricing Rules (rate contract) if configured.</li>
  <li>GST template auto-selected (In-state / Out-state) based on GSTINs.</li>
  <li>Submit when ready to send to customer.</li>
</ul>
<div class="ib-kb-note">Quotations are valid for 1 month. Daily alerts at 15, 7, and 1 day before expiry. Auto-expired past valid_till date.</div>`,
	},
	so: {
		title: "Sales Order — Confirming the Order",
		body: `
<ul class="ib-kb-steps">
  <li>Open submitted Quotation, Make, Sales Order.</li>
  <li>All dimensions, custom fields, address, and transport fields are auto-carried.</li>
  <li>Review and adjust if needed. Submit.</li>
  <li>On SO submit: assignment is marked done if customer was in daily board. Stock update broadcast fires.</li>
</ul>
<div class="ib-kb-note">SO submit is blocked if: (1) outstanding exceeds credit limit AND oldest invoice is past allowed days; OR (2) customer has the 30-day overdue block flag set.</div>
<div class="ib-kb-tip">Advance payments: on a <b>Draft</b> SO use the "Record Advance (Deposit)" button (needs Advance Approval Status = Approved before submit); on an already-<b>submitted</b> SO use a normal Payment Entry with Reference DocType = Sales Order instead — see Knowledge Base article 3.3 for both paths.</div>`,
	},
	dn: {
		title: "Delivery Note — Dispatching the Goods",
		body: `
<ul class="ib-kb-steps">
  <li>Open submitted Sales Order, Make, Delivery Note.</li>
  <li>Warehouse auto-set from location. Item dimensions pre-filled.</li>
  <li>Enter LR Number (custom_lr_number) and Transporter.</li>
  <li>System checks actual stock. If short: draft Stock Reconciliation is auto-created — submit it first, then re-submit DN.</li>
  <li>On DN submit: E-Way Bill auto-generates (if API configured). Sales person gets a bell notification with LR details.</li>
</ul>
<div class="ib-kb-tip">The IB Packing List print format shows rolls per box, carton weight, carton marking, LR number, and three signature lines.</div>`,
	},
	si: {
		title: "Sales Invoice — Billing the Customer",
		body: `
<ul class="ib-kb-steps">
  <li>Open submitted Delivery Note, Make, Sales Invoice.</li>
  <li>SI inherits the same number as the DN (DC-00005 becomes INV-00005).</li>
  <li>Optional: enter Transport Charges — GST on transport is auto-calculated per GST row rate.</li>
  <li>Submit. Then click <b>Generate e-Invoice</b> button to create the IRN from the NIC portal.</li>
  <li>Print using IB GST Tax Invoice format: 2-page output with IRN / QR code and E-Way Bill.</li>
</ul>
<div class="ib-kb-note">SI cancellation requires a Cancellation Reason. Credit Notes (returns) get a separate CN naming series.</div>`,
	},
	payment: {
		title: "Payment Entry — Recording the Collection",
		body: `
<ul class="ib-kb-steps">
  <li>Open submitted Sales Invoice, Make, Payment Entry (simplest path).</li>
  <li>Or go to Accounts, Payment Entry, New for a standalone entry.</li>
  <li>Set Payment Type = Receive, Party Type = Customer, Amount Received, Reference No.</li>
  <li>If Payment References are empty on submit: system auto-links to oldest outstanding Sales Invoices (FIFO).</li>
  <li>Submit. Accounts roles get a bell notification.</li>
</ul>
<div class="ib-kb-tip">Attaching payment screenshot: open the SI or SO, go to the bottom Attachments section, Add Attachment, Upload File or drag-and-drop.</div>
<div class="ib-kb-note">For PDC tracking: use IB PDC doctype. Alert fires 3 days before the cheque date.</div>`,
	},
};

// ── Search config ─────────────────────────────────────────────────────────────

const TYPO_MAP = {
	quatation: "quotation", quotaion: "quotation", quatotion: "quotation",
	invocie: "invoice", invoie: "invoice", invioce: "invoice",
	paymnet: "payment", payemnt: "payment", payement: "payment",
	delievry: "delivery", deliery: "delivery", dilievery: "delivery",
	cusotmer: "customer", custoemr: "customer", cutsomer: "customer",
	reprot: "report", repot: "report",
	stcok: "stock", stosk: "stock",
	einvoice: "e-invoice irn", eway: "e-way bill ewb", irn: "e-invoice irn",
	waybill: "e-way bill ewb", "e-waybill": "e-way bill ewb",
	"credit note": "credit note cn return",
	pdc: "post dated cheque pdc bank",
	fnf: "full final settlement",
	hr: "hr employee attendance payroll",
	crm: "crm lead customer prospect",
	gst: "gst tax gstin invoice",
	sla: "fulfillment sla alert 48h dispatch",
	kanban: "customer board kanban",
	ot: "overtime request hours",
	scorecard: "customer health score green amber red",
	"lead team": "lead sales team round robin assignment",
	sample: "sample request dispatch feedback",
	roster: "assignment admin roster manager",
	wo: "work order stage machine production",
	os: "order sheet production plan so",
	dpr: "daily production report stage output wastage",
	jr: "jumbo roll raw material batch traceability",
	rtd: "ready to deliver stage production notification",
	prod: "production stage work order machine",
	coating: "coating stage production jumbo roll",
	slitting: "slitting stage production",
	packing: "packing stage production qc",
	wos: "work order stage machine production",
	reorder: "reorder level low stock alert material request",
};


const SYNONYMS = {
	invoice: ["si", "bill", "billing"],
	quotation: ["quote", "estimate"],
	delivery: ["dn", "dispatch", "shipment"],
	payment: ["pe", "collection", "receipt", "money"],
	"advance approval": ["advance", "prepayment approval", "idris", "approve advance", "advance pending"],
	"line item attachment": ["row attachment", "item document", "artwork proof", "configure columns", "grid column"],
	"credit note": ["cn", "return", "refund"],
	"e-invoice": ["irn", "gst invoice"],
	"e-way bill": ["ewb", "eway", "transport"],
	attendance: ["checkin", "absent", "leave"],
	payroll: ["salary", "slip", "pf", "esic"],
	stock: ["inventory", "warehouse", "qty", "bin"],
	lead: ["prospect", "crm"],
	report: ["analytics", "dashboard", "kpi"],
	"customer board": ["kanban", "daily plan", "assignment"],
	"sample request": ["sample", "trial", "demo"],
	"sales team": ["round robin", "assignment team", "territory team", "state team"],
	target: ["goal", "quota", "monthly target"],
	dormant: ["inactive", "no order", "lapsed", "re-engage"],
	"health score": ["customer score", "health", "green amber red"],
	"overtime": ["ot", "extra hours", "overtime request"],
	"rate contract": ["pricing rule", "customer rate", "special price", "contract price"],
	"packing list": ["packing", "carton", "rolls per box"],
	"org chart": ["organization chart", "reporting structure", "hierarchy"],
	assignment: ["roster", "pool", "daily assign"],
	"work order": ["wo", "stage", "production task"],
	"order sheet": ["os", "production plan", "order plan"],
	"jumbo roll": ["jr", "raw roll", "raw material batch"],
	"production stages": ["pipeline", "kanban", "prod stages"],
	"job bundle": ["batch assign", "bundle", "group assign"],
	"machine assign": ["load balance", "machine assignment", "assign machine"],
	"wastage": ["waste", "wastage pct", "waste norm"],
	"n8n": ["removed", "automation", "workflow builder"],
	"seat map": ["live floor", "machine visualization", "roll slot map"],
};

// ── Setup ─────────────────────────────────────────────────────────────────────

function _setup_kb(wrapper, user_roles) {
	user_roles = user_roles || new Set(frappe.boot.user.roles || []);
	const $w = $(wrapper);

	const visible = KB_SECTIONS.filter(s =>
		!s.roles || !s.roles.length || s.roles.some(r => user_roles.has(r))
	);

	// Build flat search index
	const _index = [];
	visible.forEach(sec => {
		sec.items.forEach(item => {
			const blob = [
				item.title,
				item.desc || "",
				(item.steps || []).join(" "),
				item.note || "",
				item.tip || "",
				item.tags || "",
				sec.title,
			].join(" ").toLowerCase();
			_index.push({ sec, item, blob });
		});
	});

	// Update hero stat
	$w.find("#ib-kb-stat-articles").text(`${_index.length} articles`);

	_render_cats($w, visible);
	_render_sections($w, visible, _index);
	_render_recent($w, _index);
	_setup_search($w, _index, visible);
	_setup_workflow($w);
	_setup_keyboard($w);
	_setup_more_toggle($w);
	_handle_hash(visible);
}

function _setup_more_toggle($w) {
	const $btn = $w.find("#ib-kb-more-toggle");
	const $panel = $w.find("#ib-kb-more-panel");
	$btn.on("click", function () {
		$(this).toggleClass("open");
		$panel.toggleClass("open");
	});
}

// ── Category pills ────────────────────────────────────────────────────────────

const CAT_LABELS = {
	all: "All", sales: "Sales", finance: "Finance", crm: "CRM",
	gst: "GST", reports: "Reports", stock: "Stock",
	hr: "HR", ai: "AI", production: "Production", comms: "Comms",
	dashboard: "Dashboards", faq: "FAQ", reference: "Reference",
};

function _render_cats($w, visible) {
	const cats = ["all", ...new Set(visible.map(s => s.cat))];
	const $c = $w.find("#ib-kb-cats").empty();
	cats.forEach(cat => {
		$(`<button class="ib-kb-cat${cat === "all" ? " active" : ""}" data-cat="${cat}">${CAT_LABELS[cat] || cat}</button>`)
			.on("click", function () {
				$c.find(".ib-kb-cat").removeClass("active");
				$(this).addClass("active");
				const selected = $(this).data("cat");
				const $tabbar = $w.find("#ib-kb-tabbar");
				$tabbar.find(".ib-kb-tab").each(function () {
					const tab_cat = $(this).data("cat");
					$(this).toggle(selected === "all" || tab_cat === selected);
				});
				const $active = $tabbar.find(".ib-kb-tab.active");
				if (!$active.length || !$active.is(":visible")) {
					const $first = $tabbar.find(".ib-kb-tab:visible").first();
					if ($first.length) $first.trigger("click");
				}
			})
			.appendTo($c);
	});
}

// ── Sections ──────────────────────────────────────────────────────────────────

function _item_html(sec, item) {
	const _bdg = [];
	if (item.steps && item.steps.length > 1) _bdg.push(`<span class="ib-kb-badge ib-kb-badge-steps">${item.steps.length} steps</span>`);
	if (item.note) _bdg.push(`<span class="ib-kb-badge ib-kb-badge-note"><iconify-icon icon="lucide:pin" width="9" height="9"></iconify-icon> note</span>`);
	if (item.tip)  _bdg.push(`<span class="ib-kb-badge ib-kb-badge-tip"><iconify-icon icon="lucide:lightbulb" width="9" height="9"></iconify-icon> tip</span>`);
	return `
<div class="ib-kb-item" data-sec="${sec.id}" data-num="${item.num}"
     data-search="${[item.title,item.desc,item.note||"",(item.steps||[]).join(" "),item.tags||""].join(" ").replace(/<[^>]+>/g,"").replace(/"/g," ").toLowerCase()}">
  <div class="ib-kb-item-num">${item.num}</div>
  <div class="ib-kb-item-content">
    <div class="ib-kb-item-title-row">
      <span class="ib-kb-item-title">${item.title}</span>
      ${_bdg.length ? `<span class="ib-kb-item-badges">${_bdg.join("")}</span>` : ""}
    </div>
    <div class="ib-kb-item-desc">${item.desc}</div>
    ${item.link ? `<div class="ib-kb-item-footer">
      <a class="ib-kb-item-link" href="${item.link}" target="_blank"
         onclick="event.stopPropagation()">&#x2197; ${item.linkLabel || "Open"}</a>
    </div>` : ""}
  </div>
  <span class="ib-kb-item-arrow">&#x203A;</span>
</div>`;
}

function _wire_items($container, _index) {
	$container.find(".ib-kb-item").on("click", function () {
		const secId = $(this).data("sec");
		const num = $(this).data("num");
		const entry = _index.find(e => e.sec.id === secId && String(e.item.num) === String(num));
		if (entry) _open_drawer(entry.sec, entry.item, _index);
	});
}

function _render_sections($w, visible, _index) {
	const $tabbar = $w.find("#ib-kb-tabbar").empty();
	const $pane   = $w.find("#ib-kb-pane");

	let _activeId = visible.length ? visible[0].id : null;

	function _renderPane(sec) {
		if (!sec) { $pane.html(""); return; }
		$pane.html(sec.items.map(item => _item_html(sec, item)).join(""));
		_wire_items($pane, _index);
	}

	function _setActive(id) {
		_activeId = id;
		$tabbar.find(".ib-kb-tab").removeClass("active").filter(function () {
			return $(this).data("section") === id;
		}).addClass("active");
		_renderPane(visible.find(s => s.id === id));
	}

	visible.forEach((sec, si) => {
		$(`
<div class="ib-kb-tab" data-section="${sec.id}" data-cat="${sec.cat}" style="animation-delay:${si * 30}ms">
  <span class="ib-kb-tab-icon" style="background:${sec.color};color:${sec.iconColor}">${sec.icon}</span>
  <span class="ib-kb-tab-title">${sec.title}</span>
  <span class="ib-kb-tab-count" data-total="${sec.items.length}">${sec.items.length}</span>
</div>`)
			.on("click", function () { _setActive($(this).data("section")); })
			.appendTo($tabbar);
	});

	if (_activeId) _setActive(_activeId);

	$w.data("kb-set-active", _setActive);
	$w.data("kb-get-active", () => _activeId);
}

// ── Recently viewed ───────────────────────────────────────────────────────────

const RECENT_KEY = "ib_kb_recent_v2";

function _get_recent() {
	try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); }
	catch { return []; }
}

function _add_recent(sec, item) {
	const recent = _get_recent().filter(r => !(r.secId === sec.id && r.num === String(item.num)));
	recent.unshift({ secId: sec.id, num: String(item.num), title: item.title, icon: sec.icon });
	try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, 6))); }
	catch {}
}

function _render_recent($w, _index) {
	const recent = _get_recent();
	const $div = $w.find("#ib-kb-recent");
	const $chips = $w.find("#ib-kb-recent-chips").empty();
	if (!recent.length) { $div.hide(); return; }
	$div.show();
	recent.forEach(r => {
		const entry = _index.find(e => e.sec.id === r.secId && String(e.item.num) === r.num);
		if (!entry) return;
		$(`<span class="ib-kb-recent-chip">
            <span class="rci">${r.icon || entry.sec.icon}</span>
            ${_esc(r.title)}
           </span>`)
			.on("click", () => _open_drawer(entry.sec, entry.item, _index))
			.appendTo($chips);
	});
}

// ── Drawer ────────────────────────────────────────────────────────────────────

const DOCTYPE_LINKS = {
	"Sales Invoice": "/app/sales-invoice",
	"Sales Order": "/app/sales-order",
	"Delivery Note": "/app/delivery-note",
	"Quotation": "/app/quotation",
	"Payment Entry": "/app/payment-entry",
	"Purchase Invoice": "/app/purchase-invoice",
	"Customer": "/app/customer",
	"Lead": "/app/lead",
	"Employee": "/app/employee",
	"Material Request": "/app/material-request",
	"Salary Slip": "/app/salary-slip",
	"Payment Reconciliation": "/app/payment-reconciliation",
};

function _linkify(html) {
	let out = html;
	Object.entries(DOCTYPE_LINKS).forEach(([term, url]) => {
		const re = new RegExp(`\\b(${term}s?)\\b(?![^<]*>)(?![^<]*</a>)`, "g");
		out = out.replace(re, `<a href="${url}" target="_blank" class="ib-kb-doclink">$1</a>`);
	});
	return out;
}

function _open_drawer(sec, item, _index) {
	_add_recent(sec, item);

	const $bc   = $("#ib-kb-drawer-bc");
	const $body = $("#ib-kb-drawer-body");
	const $foot = $("#ib-kb-drawer-footer");

	// Breadcrumb
	$bc.html(`
<span class="ib-kb-drawer-bc-icon">${sec.icon}</span>
<span class="bc-section" style="color:${sec.iconColor}">${sec.title}</span>
<span class="bc-arrow">&#x203A;</span>
<span>${_esc(item.title)}</span>`);

	// Build body HTML
	let html = `<h2>${_esc(item.title)}</h2>`;
	if (item.updated) html += `<div class="ib-kb-updated">Updated ${_esc(item.updated)}</div>`;
	html += `<p class="desc">${_linkify(_esc(item.desc))}</p>`;

	if (item.steps && item.steps.length) {
		html += `<ol class="ib-kb-steps">`;
		item.steps.forEach(s => { html += `<li>${_linkify(s)}</li>`; });
		html += `</ol>`;
	}
	if (item.note) html += `<div class="ib-kb-note">&#128204; ${_linkify(item.note)}</div>`;
	if (item.tip)  html += `<div class="ib-kb-tip">&#128161; ${_linkify(item.tip)}</div>`;

	// Related items from same section (excluding current)
	const related = sec.items.filter(i => i.num !== item.num).slice(0, 3);
	if (related.length) {
		html += `<div class="ib-kb-related">
<div class="ib-kb-related-title">More in ${sec.title}</div>`;
		related.forEach(r => {
			html += `<div class="ib-kb-related-item" data-sec="${sec.id}" data-num="${r.num}">
<span class="ri-title">${_esc(r.title)}</span>
<span class="ri-arrow">&#x203A;</span>
</div>`;
		});
		html += `</div>`;
	}

	$body.html(html);

	// Wire related item clicks
	$body.find(".ib-kb-related-item").on("click", function () {
		const num = $(this).data("num");
		const ri = sec.items.find(i => String(i.num) === String(num));
		if (ri) _open_drawer(sec, ri, _index);
	});

	// Footer buttons
	$foot.empty();
	if (item.link) {
		$(`<a class="ib-kb-drawer-btn primary" href="${item.link}" target="_blank">
&#x2197; ${_esc(item.linkLabel || "Open in App")}
</a>`).appendTo($foot);
	}
	$(`<button class="ib-kb-drawer-btn secondary" id="ib-kb-copy-link">&#x1F517; Copy Link</button>`)
		.on("click", () => {
			const hash = `#${sec.id}/${item.num}`;
			const url = `${location.origin}${location.pathname}${hash}`;
			navigator.clipboard.writeText(url).then(() => {
				frappe.show_alert({ message: "Link copied", indicator: "green" });
			});
		})
		.appendTo($foot);

	// Prev / Next navigation
	const _itemIdx = sec.items.findIndex(i => String(i.num) === String(item.num));
	const _prevItem = _itemIdx > 0 ? sec.items[_itemIdx - 1] : null;
	const _nextItem = _itemIdx < sec.items.length - 1 ? sec.items[_itemIdx + 1] : null;
	if (_prevItem || _nextItem) {
		const $nav = $('<div class="ib-kb-drawer-nav">').appendTo($foot);
		const $prev = $(`<button class="ib-kb-nav-btn" ${!_prevItem ? "disabled" : ""}>&#x2039; ${_prevItem ? _esc(_prevItem.title.slice(0, 28)) + (_prevItem.title.length > 28 ? "…" : "") : "Previous"}</button>`)
			.on("click", () => { if (_prevItem) _open_drawer(sec, _prevItem, _index); })
			.appendTo($nav);
		const $next = $(`<button class="ib-kb-nav-btn" style="text-align:right" ${!_nextItem ? "disabled" : ""}>${_nextItem ? _esc(_nextItem.title.slice(0, 28)) + (_nextItem.title.length > 28 ? "…" : "") : "Next"} &#x203A;</button>`)
			.on("click", () => { if (_nextItem) _open_drawer(sec, _nextItem, _index); })
			.appendTo($nav);
	}

	// Update URL hash
	history.replaceState(null, "", `${location.pathname}#${sec.id}/${item.num}`);

	// Open
	$("#ib-kb-overlay").addClass("open");
	$("#ib-kb-drawer").addClass("open");

	// Trap focus
	$("#ib-kb-drawer")[0].focus();
}

function _close_drawer() {
	$("#ib-kb-overlay").removeClass("open");
	$("#ib-kb-drawer").removeClass("open");
	history.replaceState(null, "", location.pathname);
}

$(document).on("click", "#ib-kb-drawer-close, #ib-kb-overlay", _close_drawer);
$(document).on("keydown", e => {
	if (e.key === "Escape") _close_drawer();
});

// ── Search ────────────────────────────────────────────────────────────────────

function _expand_query(raw) {
	const corrected = [];
	let didCorrect = false;
	const correctionMap = {};

	raw.split(/\s+/).filter(Boolean).forEach(tok => {
		const low = tok.toLowerCase();
		if (TYPO_MAP[low]) {
			const fixed = TYPO_MAP[low];
			if (fixed !== low) { didCorrect = true; correctionMap[low] = fixed; }
			corrected.push(...fixed.split(/\s+/));
		} else {
			corrected.push(low);
		}
		// Synonym expansion
		Object.entries(SYNONYMS).forEach(([key, syns]) => {
			if (low === key || syns.includes(low)) {
				[key, ...syns].forEach(s => { if (!corrected.includes(s)) corrected.push(s); });
			}
		});
	});

	return { tokens: [...new Set(corrected)], didCorrect, correctionMap };
}

function _score(tokens, entry) {
	let score = 0;
	const titleLow = entry.item.title.toLowerCase();
	tokens.forEach(t => {
		if (!t) return;
		if (titleLow === t)            score += 12;
		else if (titleLow.startsWith(t)) score += 7;
		else if (titleLow.includes(t))   score += 5;
		else if (entry.blob.includes(t)) score += 2;
		else {
			// fuzzy prefix (min 3 chars)
			if (t.length >= 3) {
				const prefix = t.slice(0, Math.max(3, t.length - 1));
				if (entry.blob.includes(prefix)) score += 1;
			}
		}
	});
	return score;
}

function _setup_search($w, _index, visible) {
	const $input    = $w.find("#ib-kb-search");
	const $sugs     = $w.find("#ib-kb-suggestions");
	const $correct  = $w.find("#ib-kb-correction");
	const $noRes    = $w.find("#ib-kb-no-results");
	const $tabbar   = $w.find("#ib-kb-tabbar");
	const $pane     = $w.find("#ib-kb-pane");
	const $ql       = $w.find("#ib-kb-quick-links");
	const $recent   = $w.find("#ib-kb-recent");
	const $cats     = $w.find("#ib-kb-cats");
	const $wf       = $w.find(".ib-kb-workflow");

	let _timer;
	let _focused = -1;
	let _suggestions = [];

	function _reset() {
		$sugs.removeClass("open").empty();
		$correct.hide().empty();
		$noRes.hide();
		$ql.show();
		$recent.show();
		$cats.show();
		$wf.show();
		$tabbar.show();

		const setActive = $w.data("kb-set-active");
		const getActive = $w.data("kb-get-active");
		if (setActive && getActive) setActive(getActive());

		_focused = -1;
	}

	function _run_search(q) {
		q = (q || "").trim();
		if (!q) { _reset(); return; }

		const { tokens, didCorrect, correctionMap } = _expand_query(q);

		const scored = _index
			.map(e => ({ e, s: _score(tokens, e) }))
			.filter(x => x.s > 0)
			.sort((a, b) => b.s - a.s);

		_suggestions = scored.slice(0, 7);

		// Autocorrect hint
		if (didCorrect && _suggestions.length) {
			const fixed = Object.entries(correctionMap).map(([k, v]) => `<a>${v}</a>`).join(", ");
			$correct.html(`Showing results for ${fixed}`).show();
		} else {
			$correct.hide();
		}

		// Suggestions dropdown
		$sugs.empty();
		if (_suggestions.length === 0) {
			$sugs.html(`<div class="ib-kb-sug-empty">No results for "<b>${_esc(q)}</b>"</div>`);
		} else {
			_suggestions.forEach(({ e }, i) => {
				const { sec, item } = e;
				const titleHl = _highlight_text(item.title, tokens);
				const descSnip = (item.desc || "").slice(0, 80) + (item.desc.length > 80 ? "…" : "");
				$(`<div class="ib-kb-sug-item" data-idx="${i}">
<div class="ib-kb-sug-icon" style="background:${sec.color};color:${sec.iconColor}">${sec.icon}</div>
<div class="ib-kb-sug-text">
  <div class="ib-kb-sug-title">${titleHl}</div>
  <div class="ib-kb-sug-desc">${_esc(descSnip)}</div>
</div>
<div class="ib-kb-sug-section">${sec.title}</div>
</div>`).on("click", () => {
					$sugs.removeClass("open");
					$input.val("");
					_reset();
					_open_drawer(sec, item, _index);
				}).appendTo($sugs);
			});
			if (scored.length > 7) {
				$sugs.append(`<div class="ib-kb-sug-footer">${scored.length - 7} more results below</div>`);
			}
		}
		$sugs.addClass("open");
		_focused = -1;

		// Declutter while searching
		$ql.hide(); $recent.hide(); $wf.hide();
		$cats.find(".ib-kb-cat").removeClass("active");
		$cats.find(".ib-kb-cat[data-cat='all']").addClass("active");
		$tabbar.hide();

		// Flatten matches (across all sections) into the content pane
		if (scored.length === 0) {
			$pane.html("");
			$noRes.find("#ib-kb-no-q").text(`No results for "${q}"`).end().show();
			return;
		}
		$noRes.hide();

		let lastSecId = null;
		let html = "";
		scored.forEach(({ e }) => {
			if (e.sec.id !== lastSecId) {
				html += `<div class="ib-kb-pane-search-group">${_esc(e.sec.title)}</div>`;
				lastSecId = e.sec.id;
			}
			html += _item_html(e.sec, e.item);
		});
		$pane.html(html);
		_wire_items($pane, _index);
		$pane.find(".ib-kb-item").each(function () {
			_highlight($(".ib-kb-item-title", this), tokens);
			_highlight($(".ib-kb-item-desc", this), tokens);
		});
	}

	$input.on("input", function () {
		clearTimeout(_timer);
		const q = $(this).val();
		if (!q) { _reset(); return; }
		_timer = setTimeout(() => _run_search(q), 180);
	});

	// Keyboard nav in suggestions
	$input.on("keydown", function (e) {
		const items = $sugs.find(".ib-kb-sug-item");
		if (e.key === "ArrowDown") {
			e.preventDefault();
			_focused = Math.min(_focused + 1, items.length - 1);
			items.removeClass("kb-focused").eq(_focused).addClass("kb-focused");
		} else if (e.key === "ArrowUp") {
			e.preventDefault();
			_focused = Math.max(_focused - 1, -1);
			items.removeClass("kb-focused").eq(_focused).addClass("kb-focused");
		} else if (e.key === "Enter") {
			if (_focused >= 0 && _suggestions[_focused]) {
				const { sec, item } = _suggestions[_focused].e;
				$sugs.removeClass("open");
				$input.val("");
				_reset();
				_open_drawer(sec, item, _index);
			}
		} else if (e.key === "Escape") {
			$sugs.removeClass("open");
			$input.blur();
			_reset();
			$input.val("");
		}
	});

	// Close suggestions when clicking outside
	$(document).on("click.kbsearch", function (e) {
		if (!$(e.target).closest("#ib-kb-search-wrap").length) {
			$sugs.removeClass("open");
		}
	});

	// Clear search button
	$w.find("#ib-kb-clear-search").on("click", () => {
		$input.val("").trigger("input");
	});
}

// ── Workflow stepper ──────────────────────────────────────────────────────────

function _setup_workflow($w) {
	const $detail = $w.find("#ib-kb-wf-detail");
	const $title  = $w.find("#ib-kb-wf-title");
	const $body   = $w.find("#ib-kb-wf-body");

	$w.find(".ib-kb-flow-step").on("click", function () {
		const key = $(this).data("workflow");
		const wf = KB_WORKFLOWS[key];
		if (!wf) return;
		$w.find(".ib-kb-flow-step").removeClass("active");
		$(this).addClass("active");
		$title.text(wf.title);
		$body.html(wf.body);
		$detail.addClass("open");
		$detail[0].scrollIntoView({ behavior: "smooth", block: "nearest" });
	});

	$w.find("#ib-kb-wf-close").on("click", () => {
		$detail.removeClass("open");
		$w.find(".ib-kb-flow-step").removeClass("active");
	});
}

// ── Keyboard shortcut (Ctrl+K) ────────────────────────────────────────────────

function _setup_keyboard($w) {
	$(document).on("keydown.kb", function (e) {
		if ((e.ctrlKey || e.metaKey) && e.key === "k") {
			e.preventDefault();
			const $s = $w.find("#ib-kb-search");
			if ($s.length) {
				$s[0].focus();
				$s[0].select();
			}
		}
	});
}

// ── Deep link (URL hash) ──────────────────────────────────────────────────────

function _handle_hash(visible) {
	const hash = (location.hash || "").slice(1);
	if (!hash) return;
	const [secId, num] = hash.split("/");
	const sec = visible.find(s => s.id === secId);
	if (!sec) return;
	const item = num ? sec.items.find(i => String(i.num) === num) : sec.items[0];
	if (!item) return;

	// Build minimal index for drawer
	const _index = [];
	visible.forEach(s => s.items.forEach(i => {
		_index.push({ sec: s, item: i, blob: [i.title, i.desc || "", (i.steps || []).join(" "), i.tags || ""].join(" ").toLowerCase() });
	}));

	setTimeout(() => _open_drawer(sec, item, _index), 300);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function _esc(str) {
	return String(str || "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function _highlight_text(text, tokens) {
	let out = _esc(text);
	tokens.forEach(t => {
		if (!t || t.length < 2) return;
		const re = new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
		out = out.replace(re, "<mark class='ib-hl'>$1</mark>");
	});
	return out;
}

function _highlight($el, tokens) {
	$el.html(_highlight_text($el.text(), tokens));
}
