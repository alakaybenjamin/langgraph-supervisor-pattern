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

interface FieldOption {
  text: string;
  info?: string;
}

interface FieldValidation {
  minLength?: number;
  maxLength?: number;
}

interface FieldDef {
  id: string;
  text: string;
  mandatory: boolean;
  type: string;
  options?: (string | FieldOption)[];
  validation?: FieldValidation;
  info?: string;
  allowOther?: boolean;
  fileTypes?: string[];
  maxFiles?: number;
  maxFileSizeMB?: number;
}

interface QuestionTemplate {
  [section: string]: FieldDef[] | Record<string, never>;
}

// ──────────────────────────────────────────────
// State
// ──────────────────────────────────────────────

const formData: Record<string, unknown> = {};
const validationErrors: Record<string, string> = {};
let template: QuestionTemplate = {};
let activeSection = "";
let sections: string[] = [];

// ──────────────────────────────────────────────
// Section display names & icons
// ──────────────────────────────────────────────

const sectionMeta: Record<string, { label: string; icon: string }> = {
  mandatory: { label: "Mandatory", icon: "&#9733;" },
  ddf: { label: "DDF Questions", icon: "&#9776;" },
  default: { label: "Default", icon: "&#9881;" },
  onyx: { label: "Onyx", icon: "&#9670;" },
  productSpecific: { label: "Product Specific", icon: "&#9733;" },
};

// ──────────────────────────────────────────────
// Utility
// ──────────────────────────────────────────────

function escapeHtml(text: string): string {
  const el = document.createElement("span");
  el.textContent = text;
  return el.innerHTML;
}

function getOptionText(opt: string | FieldOption): string {
  return typeof opt === "string" ? opt : opt.text;
}

function getOptionInfo(opt: string | FieldOption): string | undefined {
  return typeof opt === "string" ? undefined : opt.info;
}

// ──────────────────────────────────────────────
// Render: Tabs
// ──────────────────────────────────────────────

function renderTabs(): string {
  return sections
    .map((key) => {
      const meta = sectionMeta[key] ?? {
        label: key.charAt(0).toUpperCase() + key.slice(1),
        icon: "&#9679;",
      };
      const fields = template[key];
      const count = Array.isArray(fields) ? fields.length : 0;
      const mandatoryCount = Array.isArray(fields)
        ? fields.filter((f) => f.mandatory).length
        : 0;
      const isActive = key === activeSection;

      return `
        <button class="tab ${isActive ? "tab--active" : ""}" data-section="${key}">
          <span class="tab__icon">${meta.icon}</span>
          <span class="tab__label">${escapeHtml(meta.label)}</span>
          <span class="tab__badges">
            <span class="tab__badge">${count}</span>
            ${mandatoryCount > 0 ? `<span class="tab__badge tab__badge--required">${mandatoryCount} req</span>` : ""}
          </span>
        </button>
      `;
    })
    .join("");
}

// ──────────────────────────────────────────────
// Render: Info Popover
// ──────────────────────────────────────────────

function renderInfoIcon(fieldId: string, info: string): string {
  return `
    <button class="info-trigger" type="button" data-info-id="${fieldId}" aria-label="More information">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
        <path d="M8 7v4M8 5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    </button>
    <div class="info-popover" id="info-${fieldId}" role="tooltip" hidden>
      <div class="info-popover__content">${info}</div>
    </div>
  `;
}

// ──────────────────────────────────────────────
// Render: Field Controls
// ──────────────────────────────────────────────

function renderTextField(field: FieldDef): string {
  const value = (formData[field.id] as string) ?? "";
  const error = validationErrors[field.id];
  const maxLen = field.validation?.maxLength;
  const minLen = field.validation?.minLength;

  return `
    <div class="field-control">
      <input
        type="text"
        id="field-${field.id}"
        class="input ${error ? "input--error" : ""}"
        value="${escapeHtml(value)}"
        placeholder=" "
        ${field.mandatory ? 'required' : ''}
        ${maxLen ? `maxlength="${maxLen}"` : ""}
        ${minLen ? `minlength="${minLen}"` : ""}
        data-field-id="${field.id}"
        data-field-type="text"
      />
      <label class="input__label" for="field-${field.id}">${escapeHtml(field.text)}</label>
      ${maxLen ? `<span class="input__counter">${value.length}/${maxLen}</span>` : ""}
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderTextareaField(field: FieldDef): string {
  const value = (formData[field.id] as string) ?? "";
  const error = validationErrors[field.id];
  const minLen = field.validation?.minLength;

  return `
    <div class="field-control">
      <textarea
        id="field-${field.id}"
        class="textarea ${error ? "textarea--error" : ""}"
        placeholder=" "
        rows="4"
        ${field.mandatory ? 'required' : ''}
        ${minLen ? `minlength="${minLen}"` : ""}
        data-field-id="${field.id}"
        data-field-type="textarea"
      >${escapeHtml(value)}</textarea>
      <label class="textarea__label" for="field-${field.id}">${escapeHtml(field.text)}</label>
      ${minLen ? `<span class="input__counter">${value.length} chars (min ${minLen})</span>` : ""}
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderDateRangeField(field: FieldDef): string {
  const value = (formData[field.id] as { start?: string; end?: string }) ?? {};
  const error = validationErrors[field.id];

  return `
    <div class="field-control field-control--daterange">
      <div class="daterange">
        <div class="daterange__field">
          <label class="daterange__label" for="field-${field.id}-start">Start Date</label>
          <input
            type="date"
            id="field-${field.id}-start"
            class="input input--date ${error ? "input--error" : ""}"
            value="${value.start ?? ""}"
            ${field.mandatory ? 'required' : ''}
            data-field-id="${field.id}"
            data-field-type="dateRange"
            data-date-part="start"
          />
        </div>
        <span class="daterange__separator">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M4 10h12M12 6l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <div class="daterange__field">
          <label class="daterange__label" for="field-${field.id}-end">End Date</label>
          <input
            type="date"
            id="field-${field.id}-end"
            class="input input--date ${error ? "input--error" : ""}"
            value="${value.end ?? ""}"
            ${field.mandatory ? 'required' : ''}
            data-field-id="${field.id}"
            data-field-type="dateRange"
            data-date-part="end"
          />
        </div>
      </div>
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderSelectField(field: FieldDef): string {
  const value = (formData[field.id] as string) ?? "";
  const error = validationErrors[field.id];
  const options = field.options ?? [];

  return `
    <div class="field-control">
      <select
        id="field-${field.id}"
        class="select ${error ? "select--error" : ""}"
        ${field.mandatory ? 'required' : ''}
        data-field-id="${field.id}"
        data-field-type="select"
      >
        <option value="" disabled ${!value ? "selected" : ""}>Select an option...</option>
        ${options.map((opt) => {
          const text = getOptionText(opt);
          return `<option value="${escapeHtml(text)}" ${value === text ? "selected" : ""}>${escapeHtml(text)}</option>`;
        }).join("")}
        ${field.allowOther ? `<option value="__other__" ${value === "__other__" ? "selected" : ""}>Other...</option>` : ""}
      </select>
      <label class="select__label" for="field-${field.id}">${escapeHtml(field.text)}</label>
      ${field.allowOther && value === "__other__" ? `
        <input
          type="text"
          class="input input--other"
          placeholder="Please specify..."
          data-field-id="${field.id}"
          data-field-type="selectOther"
          value="${escapeHtml((formData[`${field.id}__other`] as string) ?? "")}"
        />
      ` : ""}
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderMultiSelectField(field: FieldDef): string {
  const selected = (formData[field.id] as string[]) ?? [];
  const error = validationErrors[field.id];
  const options = field.options ?? [];

  return `
    <div class="field-control">
      <fieldset class="multiselect ${error ? "multiselect--error" : ""}">
        <legend class="multiselect__legend">${escapeHtml(field.text)}${field.mandatory ? ' <span class="required-mark">*</span>' : ""}</legend>
        <div class="multiselect__options">
          ${options.map((opt, i) => {
            const text = getOptionText(opt);
            const info = getOptionInfo(opt);
            const isChecked = selected.includes(text);
            return `
              <label class="checkbox-option ${isChecked ? "checkbox-option--checked" : ""}">
                <input
                  type="checkbox"
                  class="checkbox-option__input"
                  value="${escapeHtml(text)}"
                  ${isChecked ? "checked" : ""}
                  data-field-id="${field.id}"
                  data-field-type="multiSelect"
                />
                <span class="checkbox-option__checkmark">
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </span>
                <span class="checkbox-option__text">${escapeHtml(text)}</span>
                ${info ? renderInfoIcon(`${field.id}-opt-${i}`, info) : ""}
              </label>
            `;
          }).join("")}
        </div>
      </fieldset>
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderUserSearchField(field: FieldDef): string {
  const value = (formData[field.id] as string) ?? "";
  const error = validationErrors[field.id];

  return `
    <div class="field-control field-control--search">
      <div class="search-input">
        <svg class="search-input__icon" width="18" height="18" viewBox="0 0 18 18" fill="none">
          <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.5"/>
          <path d="M12 12l4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <input
          type="text"
          id="field-${field.id}"
          class="input input--search ${error ? "input--error" : ""}"
          value="${escapeHtml(value)}"
          placeholder="Search users by name or email..."
          ${field.mandatory ? 'required' : ''}
          data-field-id="${field.id}"
          data-field-type="user-search"
        />
      </div>
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function renderFileField(field: FieldDef): string {
  const error = validationErrors[field.id];
  const fileTypes = field.fileTypes?.map((t) => `.${t}`).join(",") ?? "";
  const fileName = (formData[field.id] as string) ?? "";

  return `
    <div class="field-control field-control--file">
      <div class="file-upload">
        <div class="file-upload__dropzone" data-field-id="${field.id}">
          <svg class="file-upload__icon" width="40" height="40" viewBox="0 0 40 40" fill="none">
            <path d="M20 6v20M12 14l8-8 8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M6 26v6a2 2 0 002 2h24a2 2 0 002-2v-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <p class="file-upload__text">
            Drag & drop or <label class="file-upload__browse" for="field-${field.id}">browse</label>
          </p>
          <p class="file-upload__hint">
            ${field.fileTypes ? `Accepted: ${field.fileTypes.join(", ").toUpperCase()}` : "Any file type"}
            ${field.maxFileSizeMB ? ` &middot; Max ${field.maxFileSizeMB}MB` : ""}
          </p>
          <input
            type="file"
            id="field-${field.id}"
            class="file-upload__input"
            ${fileTypes ? `accept="${fileTypes}"` : ""}
            ${field.mandatory ? 'required' : ''}
            data-field-id="${field.id}"
            data-field-type="file"
            hidden
          />
        </div>
        ${fileName ? `<div class="file-upload__selected"><span class="file-upload__filename">${escapeHtml(fileName)}</span><button class="file-upload__remove" data-field-id="${field.id}" type="button">&times;</button></div>` : ""}
      </div>
      ${error ? `<span class="field-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

// ──────────────────────────────────────────────
// Render: Single Field
// ──────────────────────────────────────────────

function renderField(field: FieldDef): string {
  let control: string;
  switch (field.type) {
    case "text":
      control = renderTextField(field);
      break;
    case "textarea":
      control = renderTextareaField(field);
      break;
    case "dateRange":
      control = renderDateRangeField(field);
      break;
    case "select":
      control = renderSelectField(field);
      break;
    case "multiSelect":
      control = renderMultiSelectField(field);
      break;
    case "user-search":
      control = renderUserSearchField(field);
      break;
    case "file":
      control = renderFileField(field);
      break;
    default:
      control = renderTextField(field);
  }

  const showLabel = field.type === "multiSelect" || field.type === "dateRange" || field.type === "file";

  return `
    <div class="field-card" data-field-id="${field.id}">
      ${!showLabel ? "" : `
        <div class="field-card__header">
          <span class="field-card__title">
            ${escapeHtml(field.text)}
            ${field.mandatory ? '<span class="required-mark">*</span>' : ""}
          </span>
          ${field.info ? renderInfoIcon(field.id, field.info) : ""}
        </div>
      `}
      ${showLabel ? "" : `
        <div class="field-card__header field-card__header--inline">
          ${field.mandatory ? '<span class="required-mark required-mark--dot" title="Required"></span>' : ""}
          ${field.info ? renderInfoIcon(field.id, field.info) : ""}
        </div>
      `}
      ${control}
    </div>
  `;
}

// ──────────────────────────────────────────────
// Render: Section
// ──────────────────────────────────────────────

function renderSection(): string {
  const fields = template[activeSection];
  if (!Array.isArray(fields) || fields.length === 0) {
    return `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="2" opacity="0.3"/>
          <path d="M16 24h16M24 16v16" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.3"/>
        </svg>
        <p>No fields configured for this section.</p>
      </div>
    `;
  }

  const mandatoryFields = fields.filter((f) => f.mandatory);
  const optionalFields = fields.filter((f) => !f.mandatory);
  const filledCount = fields.filter((f) => {
    const val = formData[f.id];
    if (val === undefined || val === null || val === "") return false;
    if (Array.isArray(val) && val.length === 0) return false;
    if (typeof val === "object" && !Array.isArray(val)) {
      return Object.values(val as Record<string, string>).some((v) => v);
    }
    return true;
  }).length;

  return `
    <div class="section-progress">
      <div class="section-progress__bar">
        <div class="section-progress__fill" style="width: ${fields.length > 0 ? (filledCount / fields.length) * 100 : 0}%"></div>
      </div>
      <span class="section-progress__text">${filledCount} of ${fields.length} fields completed</span>
    </div>
    ${mandatoryFields.length > 0 ? `
      <div class="field-group">
        <h3 class="field-group__title">
          <span class="field-group__icon required-mark">*</span>
          Required Fields
          <span class="field-group__count">${mandatoryFields.length}</span>
        </h3>
        ${mandatoryFields.map(renderField).join("")}
      </div>
    ` : ""}
    ${optionalFields.length > 0 ? `
      <div class="field-group">
        <h3 class="field-group__title">
          <span class="field-group__icon">&#9675;</span>
          Optional Fields
          <span class="field-group__count">${optionalFields.length}</span>
        </h3>
        ${optionalFields.map(renderField).join("")}
      </div>
    ` : ""}
  `;
}

// ──────────────────────────────────────────────
// Render: Full App
// ──────────────────────────────────────────────

function renderApp(): void {
  const main = document.querySelector(".main") as HTMLElement;
  if (!main) return;

  if (sections.length === 0) {
    main.innerHTML = `
      <div class="loading">
        <div class="loading__spinner"></div>
        <p class="loading__text">Waiting for question template...</p>
      </div>
    `;
    return;
  }

  main.innerHTML = `
    <header class="app-header">
      <h1 class="app-header__title">Question Form</h1>
      <p class="app-header__subtitle">Complete all required fields across each section</p>
    </header>
    <nav class="tabs" role="tablist">
      ${renderTabs()}
    </nav>
    <section class="section-content" role="tabpanel">
      ${renderSection()}
    </section>
    <footer class="form-actions">
      <button class="btn btn--secondary" id="btn-reset" type="button">Reset Section</button>
      <div class="form-actions__right">
        ${sections.indexOf(activeSection) > 0 ? '<button class="btn btn--outline" id="btn-prev" type="button">Previous</button>' : ""}
        ${sections.indexOf(activeSection) < sections.length - 1 ? '<button class="btn btn--primary" id="btn-next" type="button">Next Section</button>' : '<button class="btn btn--primary btn--submit" id="btn-submit" type="button">Submit Form</button>'}
      </div>
    </footer>
  `;

  attachEventListeners();
}

// ──────────────────────────────────────────────
// Validation
// ──────────────────────────────────────────────

function validateField(field: FieldDef): string | null {
  const val = formData[field.id];

  if (field.mandatory) {
    if (val === undefined || val === null || val === "") {
      return "This field is required";
    }
    if (Array.isArray(val) && val.length === 0) {
      return "Please select at least one option";
    }
    if (field.type === "dateRange") {
      const dv = val as { start?: string; end?: string };
      if (!dv.start || !dv.end) return "Both start and end dates are required";
    }
  }

  if (typeof val === "string" && val.length > 0 && field.validation) {
    if (field.validation.minLength && val.length < field.validation.minLength) {
      return `Minimum ${field.validation.minLength} characters required (${val.length} entered)`;
    }
    if (field.validation.maxLength && val.length > field.validation.maxLength) {
      return `Maximum ${field.validation.maxLength} characters allowed`;
    }
  }

  if (field.type === "dateRange" && val) {
    const dv = val as { start?: string; end?: string };
    if (dv.start && dv.end && dv.start > dv.end) {
      return "End date must be after start date";
    }
  }

  return null;
}

function validateSection(): boolean {
  const fields = template[activeSection];
  if (!Array.isArray(fields)) return true;

  let valid = true;
  for (const field of fields) {
    const error = validateField(field);
    if (error) {
      validationErrors[field.id] = error;
      valid = false;
    } else {
      delete validationErrors[field.id];
    }
  }
  return valid;
}

// ──────────────────────────────────────────────
// Event Listeners
// ──────────────────────────────────────────────

function attachEventListeners(): void {
  // Tab clicks
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeSection = btn.dataset.section!;
      renderApp();
    });
  });

  // Text / textarea inputs
  document
    .querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
      '[data-field-type="text"], [data-field-type="textarea"], [data-field-type="user-search"], [data-field-type="selectOther"]',
    )
    .forEach((el) => {
      el.addEventListener("input", () => {
        const id = el.dataset.fieldId!;
        if (el.dataset.fieldType === "selectOther") {
          formData[`${id}__other`] = el.value;
        } else {
          formData[id] = el.value;
        }
        delete validationErrors[id];
        updateFieldUI(el);
      });

      el.addEventListener("blur", () => {
        const id = el.dataset.fieldId!;
        const fields = template[activeSection];
        if (!Array.isArray(fields)) return;
        const field = fields.find((f) => f.id === id);
        if (field) {
          const error = validateField(field);
          if (error) {
            validationErrors[id] = error;
          } else {
            delete validationErrors[id];
          }
          updateFieldUI(el);
        }
      });
    });

  // Date range inputs
  document
    .querySelectorAll<HTMLInputElement>('[data-field-type="dateRange"]')
    .forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.fieldId!;
        const part = el.dataset.datePart!;
        const current = (formData[id] as { start?: string; end?: string }) ?? {};
        current[part as "start" | "end"] = el.value;
        formData[id] = current;
        delete validationErrors[id];
      });
    });

  // Select inputs
  document
    .querySelectorAll<HTMLSelectElement>('[data-field-type="select"]')
    .forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.fieldId!;
        formData[id] = el.value;
        delete validationErrors[id];
        renderApp();
      });
    });

  // Multi-select checkboxes
  document
    .querySelectorAll<HTMLInputElement>('[data-field-type="multiSelect"]')
    .forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.fieldId!;
        const current = (formData[id] as string[]) ?? [];
        if (el.checked) {
          formData[id] = [...current, el.value];
        } else {
          formData[id] = current.filter((v) => v !== el.value);
        }
        delete validationErrors[id];
        const label = el.closest(".checkbox-option");
        if (label) {
          label.classList.toggle("checkbox-option--checked", el.checked);
        }
      });
    });

  // File inputs
  document
    .querySelectorAll<HTMLInputElement>('[data-field-type="file"]')
    .forEach((el) => {
      el.addEventListener("change", () => {
        const id = el.dataset.fieldId!;
        if (el.files && el.files.length > 0) {
          formData[id] = el.files[0].name;
          delete validationErrors[id];
          renderApp();
        }
      });
    });

  // File remove buttons
  document
    .querySelectorAll<HTMLButtonElement>(".file-upload__remove")
    .forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.fieldId!;
        delete formData[id];
        renderApp();
      });
    });

  // Info popover toggles
  document.querySelectorAll<HTMLButtonElement>(".info-trigger").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const infoId = btn.dataset.infoId!;
      const popover = document.getElementById(`info-${infoId}`);
      if (popover) {
        const isHidden = popover.hasAttribute("hidden");
        document
          .querySelectorAll(".info-popover:not([hidden])")
          .forEach((p) => p.setAttribute("hidden", ""));
        if (isHidden) {
          popover.removeAttribute("hidden");
        }
      }
    });
  });

  // Close popovers on outside click
  document.addEventListener("click", () => {
    document
      .querySelectorAll(".info-popover:not([hidden])")
      .forEach((p) => p.setAttribute("hidden", ""));
  });

  // Navigation buttons
  document.getElementById("btn-next")?.addEventListener("click", () => {
    if (validateSection()) {
      const idx = sections.indexOf(activeSection);
      if (idx < sections.length - 1) {
        activeSection = sections[idx + 1];
        renderApp();
      }
    } else {
      renderApp();
      scrollToFirstError();
    }
  });

  document.getElementById("btn-prev")?.addEventListener("click", () => {
    const idx = sections.indexOf(activeSection);
    if (idx > 0) {
      activeSection = sections[idx - 1];
      renderApp();
    }
  });

  document.getElementById("btn-reset")?.addEventListener("click", () => {
    const fields = template[activeSection];
    if (Array.isArray(fields)) {
      for (const field of fields) {
        delete formData[field.id];
        delete formData[`${field.id}__other`];
        delete validationErrors[field.id];
      }
    }
    renderApp();
  });

  document.getElementById("btn-submit")?.addEventListener("click", async () => {
    let allValid = true;
    for (const key of sections) {
      const fields = template[key];
      if (!Array.isArray(fields)) continue;
      for (const field of fields) {
        const error = validateField(field);
        if (error) {
          validationErrors[field.id] = error;
          allValid = false;
        } else {
          delete validationErrors[field.id];
        }
      }
    }

    if (!allValid) {
      for (const key of sections) {
        const fields = template[key];
        if (!Array.isArray(fields)) continue;
        if (fields.some((f) => validationErrors[f.id])) {
          activeSection = key;
          break;
        }
      }
      renderApp();
      scrollToFirstError();
      return;
    }

    await submitForm();
  });
}

function updateFieldUI(el: HTMLElement): void {
  const id = el.dataset.fieldId!;
  const card = el.closest(".field-card");
  const error = validationErrors[id];

  const existingError = card?.querySelector(".field-error");
  if (existingError) existingError.remove();

  if (error) {
    el.classList.add("input--error", "textarea--error");
    const errorEl = document.createElement("span");
    errorEl.className = "field-error";
    errorEl.textContent = error;
    el.closest(".field-control")?.appendChild(errorEl);
  } else {
    el.classList.remove("input--error", "textarea--error");
  }
}

function scrollToFirstError(): void {
  const firstError = document.querySelector(".field-error");
  firstError?.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ──────────────────────────────────────────────
// Submit
// ──────────────────────────────────────────────

async function submitForm(): Promise<void> {
  const submitBtn = document.getElementById("btn-submit") as HTMLButtonElement;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";
  }

  const summary = sections
    .map((key) => {
      const fields = template[key];
      if (!Array.isArray(fields)) return "";
      const entries = fields
        .map((f) => {
          const val = formData[f.id];
          if (val === undefined || val === null || val === "") return null;
          const display =
            typeof val === "object" ? JSON.stringify(val) : String(val);
          return `  - ${f.text}: ${display}`;
        })
        .filter(Boolean);
      if (entries.length === 0) return "";
      const meta = sectionMeta[key] ?? { label: key };
      return `**${meta.label}**\n${entries.join("\n")}`;
    })
    .filter(Boolean)
    .join("\n\n");

  try {
    await mcpApp.updateModelContext({
      content: [
        {
          type: "text",
          text: `## Question Form Submission\n\n${summary}\n\n---\n*Submitted at ${new Date().toISOString()}*`,
        },
      ],
    });

    await mcpApp.sendMessage({
      role: "user",
      content: [
        {
          type: "text",
          text: "I have completed and submitted the question form. Please review my responses.",
        },
      ],
    });

    const main = document.querySelector(".main") as HTMLElement;
    main.innerHTML = `
      <div class="success-state">
        <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
          <circle cx="32" cy="32" r="28" stroke="var(--color-accent)" stroke-width="3"/>
          <path d="M20 32l8 8 16-16" stroke="var(--color-accent)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h2>Form Submitted Successfully</h2>
        <p>Your responses have been recorded and sent for review.</p>
      </div>
    `;
  } catch (err) {
    console.error("Submit error:", err);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit Form";
    }
  }
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

function loadTemplate(result: CallToolResult): void {
  const structured = result.structuredContent as {
    template?: QuestionTemplate;
  } | null;

  if (!structured?.template) return;

  template = structured.template;
  sections = Object.keys(template).filter((k) => {
    const val = template[k];
    return Array.isArray(val) && val.length > 0;
  });

  if (sections.length > 0 && !activeSection) {
    activeSection = sections[0];
  }

  renderApp();
}

const mcpApp = new App({ name: "Question Form App", version: "1.0.0" });

mcpApp.onteardown = async () => {
  return {};
};

mcpApp.ontoolinput = (params) => {
  console.info("Received tool input:", params);
};

mcpApp.ontoolresult = (result) => {
  console.info("Received tool result:", result);
  loadTemplate(result);
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
