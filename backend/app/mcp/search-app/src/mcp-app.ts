import {
  App,
  applyDocumentTheme,
  applyHostFonts,
  applyHostStyleVariables,
  type McpUiHostContext,
} from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import "./global.css";

// ──────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────

interface Product {
  id: string;
  title: string;
  description: string;
  domain: string;
  product_type: string;
  sensitivity: string;
  owner: string;
}

interface FacetOption {
  id: string;
  label: string;
}

interface Facets {
  domains: FacetOption[];
  product_types: FacetOption[];
  sensitivities: FacetOption[];
}

// ──────────────────────────────────────────────
// State
// ──────────────────────────────────────────────

let allProducts: Product[] = [];
let filteredProducts: Product[] = [];
let facets: Facets = { domains: [], product_types: [], sensitivities: [] };
let selectedIds = new Set<string>();
let dataLoaded = false;

let filterDomain = "all";
let filterType = "all";
let filterSensitivity = "all";
let searchQuery = "";

// ──────────────────────────────────────────────
// Utility
// ──────────────────────────────────────────────

function escapeHtml(text: string): string {
  const el = document.createElement("span");
  el.textContent = text;
  return el.innerHTML;
}

function applyFilters(): void {
  filteredProducts = allProducts.filter((p) => {
    if (filterDomain !== "all" && p.domain !== filterDomain) return false;
    if (filterType !== "all" && p.product_type !== filterType) return false;
    if (filterSensitivity !== "all" && p.sensitivity !== filterSensitivity) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        p.title.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q) ||
        p.owner.toLowerCase().includes(q)
      );
    }
    return true;
  });
}

function sensitivityClass(s: string): string {
  if (s === "critical") return "product-tag--sensitivity-critical";
  if (s === "high") return "product-tag--sensitivity-high";
  return "product-tag--sensitivity-medium";
}

// ──────────────────────────────────────────────
// Render
// ──────────────────────────────────────────────

function renderFilterChips(): string {
  const chips: string[] = [];
  if (filterDomain !== "all") {
    const label = facets.domains.find((d) => d.id === filterDomain)?.label ?? filterDomain;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}<button class="filter-chip__remove" data-clear="domain">&times;</button></span>`);
  }
  if (filterType !== "all") {
    const label = facets.product_types.find((t) => t.id === filterType)?.label ?? filterType;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}<button class="filter-chip__remove" data-clear="type">&times;</button></span>`);
  }
  if (filterSensitivity !== "all") {
    const label = facets.sensitivities.find((s) => s.id === filterSensitivity)?.label ?? filterSensitivity;
    chips.push(`<span class="filter-chip">${escapeHtml(label)}<button class="filter-chip__remove" data-clear="sensitivity">&times;</button></span>`);
  }
  return chips.length > 0 ? `<div class="active-filters">${chips.join("")}</div>` : "";
}

function renderProductCard(product: Product): string {
  const selected = selectedIds.has(product.id);
  return `
    <div class="product-card ${selected ? "product-card--selected" : ""}" data-product-id="${product.id}">
      <div class="product-card__checkbox">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M2 7l4 4 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="product-card__body">
        <div class="product-card__title">
          ${escapeHtml(product.title)}
          <span class="product-card__id">${escapeHtml(product.id)}</span>
        </div>
        <div class="product-card__description">${escapeHtml(product.description)}</div>
        <div class="product-card__tags">
          <span class="product-tag product-tag--domain">${escapeHtml(product.domain.replace("_", " "))}</span>
          <span class="product-tag product-tag--type">${escapeHtml(product.product_type.toUpperCase())}</span>
          <span class="product-tag ${sensitivityClass(product.sensitivity)}">${escapeHtml(product.sensitivity)}</span>
        </div>
      </div>
    </div>
  `;
}

function renderApp(): void {
  const main = document.querySelector(".main") as HTMLElement;
  if (!main) return;

  if (!dataLoaded) {
    main.innerHTML = `
      <div class="loading">
        <div class="loading__spinner"></div>
        <p class="loading__text">Loading data products...</p>
      </div>
    `;
    return;
  }

  applyFilters();

  const productCards = filteredProducts.length > 0
    ? filteredProducts.map(renderProductCard).join("")
    : `<div class="empty-state">
         <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
           <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="2" opacity="0.3"/>
           <path d="M16 24h16M24 16v16" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.3"/>
         </svg>
         <p>No products match your filters.</p>
         <button class="btn btn--secondary" id="btn-clear-all">Clear All Filters</button>
       </div>`;

  main.innerHTML = `
    <header class="app-header">
      <h1 class="app-header__title">Search Data Products</h1>
      <p class="app-header__subtitle">Find and select data products for your access request</p>
    </header>

    <div class="search-bar">
      <svg class="search-bar__icon" width="18" height="18" viewBox="0 0 18 18" fill="none">
        <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.5"/>
        <path d="M12 12l4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <input
        type="text"
        class="search-bar__input"
        id="search-input"
        placeholder="Search by name, ID, or description..."
        value="${escapeHtml(searchQuery)}"
      />
      ${searchQuery ? '<button class="search-bar__clear" id="btn-clear-search">&times;</button>' : ""}
    </div>

    <div class="filters">
      <div class="filter-group">
        <span class="filter-group__label">Domain</span>
        <select class="filter-select" id="filter-domain">
          <option value="all">All Domains</option>
          ${facets.domains.map((d) => `<option value="${d.id}" ${filterDomain === d.id ? "selected" : ""}>${escapeHtml(d.label)}</option>`).join("")}
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-group__label">Type</span>
        <select class="filter-select" id="filter-type">
          <option value="all">Any Type</option>
          ${facets.product_types.map((t) => `<option value="${t.id}" ${filterType === t.id ? "selected" : ""}>${escapeHtml(t.label)}</option>`).join("")}
        </select>
      </div>
      <div class="filter-group">
        <span class="filter-group__label">Sensitivity</span>
        <select class="filter-select" id="filter-sensitivity">
          <option value="all">Any Level</option>
          ${facets.sensitivities.map((s) => `<option value="${s.id}" ${filterSensitivity === s.id ? "selected" : ""}>${escapeHtml(s.label)}</option>`).join("")}
        </select>
      </div>
    </div>

    ${renderFilterChips()}

    <div class="results-header">
      <span class="results-header__count">${filteredProducts.length} product(s) found</span>
      ${selectedIds.size > 0 ? `<span class="results-header__selected">${selectedIds.size} selected</span>` : ""}
    </div>

    <div class="product-list">
      ${productCards}
    </div>

    <div class="footer-actions">
      <span class="footer-actions__info">
        ${selectedIds.size > 0 ? `${selectedIds.size} product(s) selected` : "Select products to continue"}
      </span>
      <div class="footer-actions__buttons">
        <button class="btn btn--secondary" id="btn-cancel">Cancel</button>
        <button class="btn btn--primary" id="btn-confirm" ${selectedIds.size === 0 ? "disabled" : ""}>
          Add ${selectedIds.size > 0 ? `(${selectedIds.size})` : ""} to Request
        </button>
      </div>
    </div>
  `;

  attachEventListeners();
}

// ──────────────────────────────────────────────
// Event Listeners
// ──────────────────────────────────────────────

let searchDebounce: ReturnType<typeof setTimeout> | null = null;

function attachEventListeners(): void {
  const searchInput = document.getElementById("search-input") as HTMLInputElement;
  searchInput?.addEventListener("input", () => {
    if (searchDebounce) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      searchQuery = searchInput.value;
      renderApp();
    }, 250);
  });

  document.getElementById("btn-clear-search")?.addEventListener("click", () => {
    searchQuery = "";
    renderApp();
  });

  document.getElementById("filter-domain")?.addEventListener("change", (e) => {
    filterDomain = (e.target as HTMLSelectElement).value;
    renderApp();
  });
  document.getElementById("filter-type")?.addEventListener("change", (e) => {
    filterType = (e.target as HTMLSelectElement).value;
    renderApp();
  });
  document.getElementById("filter-sensitivity")?.addEventListener("change", (e) => {
    filterSensitivity = (e.target as HTMLSelectElement).value;
    renderApp();
  });

  document.querySelectorAll<HTMLButtonElement>(".filter-chip__remove").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const key = btn.dataset.clear;
      if (key === "domain") filterDomain = "all";
      else if (key === "type") filterType = "all";
      else if (key === "sensitivity") filterSensitivity = "all";
      renderApp();
    });
  });

  document.getElementById("btn-clear-all")?.addEventListener("click", () => {
    filterDomain = "all";
    filterType = "all";
    filterSensitivity = "all";
    searchQuery = "";
    renderApp();
  });

  document.querySelectorAll<HTMLDivElement>(".product-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = card.dataset.productId!;
      if (selectedIds.has(id)) {
        selectedIds.delete(id);
      } else {
        selectedIds.add(id);
      }
      renderApp();
    });
  });

  document.getElementById("btn-cancel")?.addEventListener("click", async () => {
    await mcpApp.sendMessage({
      role: "user",
      content: [{ type: "text", text: "Cancel search — go back to conversation." }],
    });
  });

  document.getElementById("btn-confirm")?.addEventListener("click", async () => {
    if (selectedIds.size === 0) return;

    const selected = allProducts.filter((p) => selectedIds.has(p.id));

    const selectedForGraph = selected.map((p) => ({
      content: p.description,
      metadata: {
        id: p.id,
        domain: p.domain,
        product_type: p.product_type,
        sensitivity: p.sensitivity,
        owner: p.owner,
      },
      score: 1.0,
    }));

    const summary = selected.map((p) => `- **${p.id}**: ${p.title}`).join("\n");

    await mcpApp.updateModelContext({
      content: [
        {
          type: "text",
          text: `## Selected Data Products\n\n${summary}`,
        },
      ],
    });

    await mcpApp.sendMessage({
      role: "user",
      content: [
        {
          type: "text",
          text: JSON.stringify({
            action: "select_products",
            selected_products: selectedForGraph,
          }),
        },
      ],
    });
  });
}

// ──────────────────────────────────────────────
// MCP App Lifecycle
// ──────────────────────────────────────────────

function handleHostContextChanged(ctx: McpUiHostContext): void {
  const main = document.querySelector(".main") as HTMLElement;
  if (ctx.theme) applyDocumentTheme(ctx.theme);
  if (ctx.styles?.variables) applyHostStyleVariables(ctx.styles.variables);
  if (ctx.styles?.css?.fonts) applyHostFonts(ctx.styles.css.fonts);
  if (ctx.safeAreaInsets && main) {
    main.style.paddingTop = `${ctx.safeAreaInsets.top}px`;
    main.style.paddingRight = `${ctx.safeAreaInsets.right}px`;
    main.style.paddingBottom = `${ctx.safeAreaInsets.bottom}px`;
    main.style.paddingLeft = `${ctx.safeAreaInsets.left}px`;
  }
}

function loadSearchData(result: CallToolResult): void {
  const structured = result.structuredContent as {
    products?: Product[];
    facets?: Facets;
    appliedFilters?: Record<string, string>;
  } | null;

  if (!structured) {
    dataLoaded = true;
    renderApp();
    return;
  }

  allProducts = structured.products ?? [];
  if (structured.facets) {
    facets = structured.facets;
  }
  if (structured.appliedFilters) {
    filterDomain = structured.appliedFilters.domain ?? "all";
    filterType = structured.appliedFilters.product_type ?? "all";
    filterSensitivity = structured.appliedFilters.sensitivity ?? "all";
  }

  dataLoaded = true;
  renderApp();
}

const mcpApp = new App({ name: "Data Product Search", version: "1.0.0" });

mcpApp.onteardown = async () => ({});

mcpApp.ontoolinput = (params) => {
  console.info("Received tool input:", params);
};

mcpApp.ontoolresult = (result) => {
  console.info("Received tool result:", result);
  loadSearchData(result);
};

mcpApp.ontoolinputpartial = (params) => {
  console.info("Partial input:", params);
};

mcpApp.ontoolcancelled = (params) => {
  console.info("Tool cancelled:", params.reason);
};

mcpApp.onerror = console.error;
mcpApp.onhostcontextchanged = handleHostContextChanged;

renderApp();

mcpApp.connect().then(() => {
  const ctx = mcpApp.getHostContext();
  if (ctx) handleHostContextChanged(ctx);
});
