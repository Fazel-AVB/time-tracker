"""
"New subject" picker: three suggestion boxes (Subject, Low Label, High Label)
and an Add button, as ONE custom component.

Each box, while focused, lists earlier values filtered by case-insensitive
starts-with; clicking a value fills it in, typing a new value is allowed, and
each listed value has a ✕ that reports a removal to Python.

Built on st.components.v2 because a native st.selectbox cannot put a button
inside its option list (checked up to Streamlit 1.64); tested on 1.56.

Deliberately one component, not three boxes plus st.button: a per-box value
sent on blur triggers a rerun that swallows the Add click made right after
typing (reproduced in a browser: the first click saved nothing). Here Add
sends all three values in a single trigger, and nothing reruns while typing.
The option lists float over the content below (see .sb-list) so opening
and closing them never moves the Add button.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import streamlit as st

_HTML = '<div class="sb-root"></div>'

_CSS = """
.sb-root { font-family: inherit; }
.sb-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
@media (max-width: 640px) { .sb-grid { grid-template-columns: 1fr; } }
.sb-add {
    margin-top: 0.75rem; width: 100%; padding: 0.5rem; border-radius: 0.5rem; font: inherit;
    border: 1px solid var(--st-border-color, #C4B5FD); cursor: pointer;
    background: var(--st-background-color, #F5F3FF); color: var(--st-text-color, #1E1B4B);
}
.sb-add:hover:not(:disabled) { border-color: var(--st-primary-color, #7C3AED); color: var(--st-primary-color, #7C3AED); }
.sb-add:disabled { opacity: 0.5; cursor: not-allowed; }
.sb-label { font-size: 0.875rem; margin-bottom: 0.25rem; color: var(--st-text-color, #1E1B4B); }
.sb-input {
    width: 100%; box-sizing: border-box; padding: 0.5rem 0.75rem;
    border: 1px solid var(--st-border-color, #C4B5FD); border-radius: 0.5rem;
    background: var(--st-secondary-background-color, #EDE9FE);
    color: var(--st-text-color, #1E1B4B); font: inherit; font-size: 1rem; outline: none;
}
.sb-input:focus { border-color: var(--st-primary-color, #7C3AED); }
.sb-field { position: relative; }
/* Floating, not inline: an inline list collapsing on blur shifted the Add
   button up between mousedown and click, so the click was lost. */
.sb-list {
    position: absolute; left: 0; right: 0; top: 100%; z-index: 1000;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    list-style: none; margin: 0.25rem 0 0; padding: 0.25rem 0;
    border: 1px solid var(--st-border-color, #C4B5FD); border-radius: 0.5rem;
    max-height: 13rem; overflow-y: auto; background: var(--st-background-color, #F5F3FF);
}
.sb-item { display: flex; align-items: center; justify-content: space-between;
           padding: 0.3rem 0.75rem; cursor: pointer; }
.sb-item.active, .sb-item:hover { background: var(--st-secondary-background-color, #EDE9FE); }
.sb-remove {
    border: none; background: transparent; cursor: pointer; font-size: 0.9rem;
    color: var(--st-text-color, #1E1B4B); opacity: 0.55; padding: 0 0.25rem;
}
.sb-remove:hover { opacity: 1; color: #DC2626; }
.sb-empty { padding: 0.3rem 0.75rem; opacity: 0.6; font-size: 0.875rem; }
"""

# The JS function runs again on every rerun. The DOM is built only once per
# mount and just refreshed afterwards: rebuilding it would wipe the text being
# typed. The latest options and setters are read from `root.sb` on each use,
# because each run hands in fresh ones.
_JS = """
export default function (component) {
  const { parentElement, data, setTriggerValue } = component;
  const root = parentElement.querySelector('.sb-root');
  const firstRun = !root.sb;
  root.sb = Object.assign(root.sb || { boxes: [] }, { data, setTriggerValue });
  const sb = root.sb;

  const makeBox = (field, grid, onChange) => {
    const box = { column: field.column, open: false, active: -1 };
    const wrap = document.createElement('div');
    const field_ = document.createElement('div');
    field_.className = 'sb-field';
    const label = document.createElement('div');
    label.className = 'sb-label';
    label.textContent = field.label;
    const input = document.createElement('input');
    input.className = 'sb-input';
    input.placeholder = sb.data.placeholder || '';
    input.setAttribute('aria-label', field.label);
    const list = document.createElement('ul');
    list.className = 'sb-list';
    list.style.display = 'none';
    field_.append(input, list);
    wrap.append(label, field_);
    grid.append(wrap);
    box.input = input;

    const options = () => (sb.data.fields.find((f) => f.column === box.column) || {}).options || [];
    // Case-insensitive starts-with, matching filter_mode="prefix" elsewhere.
    const matches = () => {
      const q = input.value.trim().toLowerCase();
      return options().filter((o) => o.toLowerCase().startsWith(q));
    };
    const pick = (value) => { input.value = value; box.open = false; box.render(); onChange(); };

    box.render = () => {
      const items = matches();
      list.innerHTML = '';
      if (!box.open) { list.style.display = 'none'; return; }
      list.style.display = 'block';
      if (items.length === 0) {
        const li = document.createElement('li');
        li.className = 'sb-empty';
        li.textContent = input.value.trim() ? 'New value' : 'No saved values yet';
        list.append(li);
        return;
      }
      items.forEach((opt, i) => {
        const li = document.createElement('li');
        li.className = 'sb-item' + (i === box.active ? ' active' : '');
        const text = document.createElement('span');
        text.textContent = opt;
        const x = document.createElement('button');
        x.className = 'sb-remove';
        x.type = 'button';
        x.textContent = '✕';
        x.title = 'Remove "' + opt + '" from the suggestions';
        x.setAttribute('aria-label', 'Remove ' + opt);
        // preventDefault on mousedown keeps focus in the input, so blur does
        // not close the list before the click lands.
        x.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
        x.addEventListener('click', (e) => {
          e.stopPropagation();
          sb.setTriggerValue('removed', { column: box.column, value: opt });
        });
        li.addEventListener('mousedown', (e) => e.preventDefault());
        li.addEventListener('click', () => pick(opt));
        li.append(text, x);
        list.append(li);
      });
    };

    input.addEventListener('focus', () => { box.open = true; box.active = -1; box.render(); });
    input.addEventListener('input', () => { box.open = true; box.active = -1; box.render(); onChange(); });
    input.addEventListener('blur', () => { box.open = false; box.render(); });
    input.addEventListener('keydown', (e) => {
      const items = matches();
      if (e.key === 'ArrowDown') { e.preventDefault(); box.open = true; box.active = Math.min(box.active + 1, items.length - 1); box.render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); box.active = Math.max(box.active - 1, 0); box.render(); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (box.open && box.active >= 0 && items[box.active]) pick(items[box.active]);
        else { box.open = false; box.render(); }
      } else if (e.key === 'Escape') { box.open = false; box.render(); }
    });
    return box;
  };

  if (firstRun) {
    const grid = document.createElement('div');
    grid.className = 'sb-grid';
    const add = document.createElement('button');
    add.className = 'sb-add';
    add.type = 'button';
    add.textContent = sb.data.button_label || 'Add';
    root.append(grid, add);
    // Add is enabled only when every box has text, so Python never receives
    // a half-filled subject.
    const refresh = () => { add.disabled = !sb.boxes.every((b) => b.input.value.trim()); };
    sb.boxes = sb.data.fields.map((f) => makeBox(f, grid, refresh));
    refresh();
    add.addEventListener('click', () => {
      const values = {};
      sb.boxes.forEach((b) => { values[b.column] = b.input.value.trim(); });
      sb.setTriggerValue('add', values);
      // Clear right away; Python re-validates and reports any problem.
      sb.boxes.forEach((b) => { b.input.value = ''; });
      refresh();
    });
  }

  // Refresh open lists with this run's options (e.g. after a ✕ removed one).
  sb.boxes.forEach((b) => b.render());
}
"""

_new_subject_picker = st.components.v2.component(
    "new_subject_picker", html=_HTML, css=_CSS, js=_JS)


def new_subject_picker(
    suggestions: Dict[str, List[str]],
    key: str,
    button_label: str = "Add to this week",
    placeholder: str = "Type or pick…",
) -> tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    """
    Render the picker. `suggestions` maps column name -> options, in display
    order (build_suggestions output). Returns (added, removed), each set only
    on the run right after the user acted:
    added   - {column: typed value} when Add was clicked, else None;
    removed - {"column": ..., "value": ...} when a ✕ was clicked, else None.
    """
    result = _new_subject_picker(
        key=key,
        data={
            "fields": [{"column": c, "label": c, "options": list(v)} for c, v in suggestions.items()],
            "placeholder": placeholder,
            "button_label": button_label,
        },
        on_add_change=lambda: None,
        on_removed_change=lambda: None,
    )
    return result.get("add"), result.get("removed")
