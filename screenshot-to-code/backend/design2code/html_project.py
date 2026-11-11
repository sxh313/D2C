"""Package upstream classic HTML/JS as CSP-compatible local build sources."""
import json
import re
from html import escape
from html.parser import HTMLParser


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.markup: list[str] = []
        self.scripts: list[str] = []
        self.handlers: list[tuple[str, list[tuple[str, str]]]] = []
        self.script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            kind = (values.get("type") or "").strip().lower()
            if values.get("src") or kind == "module":
                raise ValueError("HTML 工程仅支持内置经典脚本；外部或 module 脚本不能在当前离线模板中执行。")
            if kind in {"", "text/javascript", "application/javascript"}:
                self.script = []
                return
        handlers = [(key[2:], value) for key, value in attrs
                    if re.fullmatch(r"on[a-z]+", key) and value is not None]
        if not handlers:
            self.markup.append(self.get_starttag_text() or "")
            return
        marker = f"d2c-{len(self.handlers)}"
        self.handlers.append((marker, handlers))
        safe_attrs = [(key, value) for key, value in attrs
                      if not re.fullmatch(r"on[a-z]+", key) and key != "data-d2c-handler"]
        safe_attrs.append(("data-d2c-handler", marker))
        self.markup.append("<" + tag + "".join(" " + key if value is None else
            f' {key}="{escape(value, quote=True)}"' for key, value in safe_attrs) + ">")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.script is not None:
            self.scripts.append("".join(self.script))
            self.script = None
        else:
            self.markup.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        (self.script if self.script is not None else self.markup).append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.handle_data(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.markup.append(f"<!{decl}>")


def html_project(html: str) -> list[dict[str, str]]:
    page = _Page()
    page.feed(html)
    page.close()
    if page.script is not None:
        raise ValueError("HTML 脚本未闭合，无法打包。")
    # JS is compiled into the local bundle, never eval/new Function/inline DOM
    # scripts. Defer DOMContentLoaded listeners until all scripts have mounted.
    runtime = """export function mountAgentPage() {
  const __d2cReady = [];
  const document = new Proxy(window.document, {
    get(target, key) {
      if (key === 'addEventListener') return (type, callback, options) => {
        if (type === 'DOMContentLoaded') { __d2cReady.push(callback); return; }
        target.addEventListener(type, callback, options);
      };
      if (key === 'removeEventListener') return (type, callback, options) => {
        if (type === 'DOMContentLoaded') {
          const index = __d2cReady.indexOf(callback); if (index >= 0) __d2cReady.splice(index, 1); return;
        }
        target.removeEventListener(type, callback, options);
      };
      const value = Reflect.get(target, key, target);
      return typeof value === 'function' ? value.bind(target) : value;
    }
  });
"""
    runtime += "\n;\n".join(page.scripts) + "\n"
    for marker, handlers in page.handlers:
        for event, code in handlers:
            runtime += f"""{{
  const node = document.querySelector('[data-d2c-handler="{marker}"]');
  node?.addEventListener({json.dumps(event)}, function(event) {{
    const outcome = (function(event) {{ {code}\n }}).call(this, event);
    if (outcome === false) event.preventDefault();
  }});
}}
"""
    runtime += """  for (const callback of __d2cReady) {
    const event = new Event('DOMContentLoaded');
    if (typeof callback === 'function') callback.call(window.document, event);
    else callback?.handleEvent(event);
  }
}
"""
    app = """import { useEffect, useRef } from 'react';
import { mountAgentPage } from './agent-runtime.js';
import './index.css';
const markup = """ + json.dumps("".join(page.markup), ensure_ascii=True) + """;
export default function App() {
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    mountAgentPage();
  }, []);
  return <div className="d2c-agent-output" dangerouslySetInnerHTML={{ __html: markup }} />;
}
"""
    return [{"path": "src/App.tsx", "content": app},
            {"path": "src/agent-runtime.js", "content": runtime},
            {"path": "src/agent-runtime.d.ts", "content": "export function mountAgentPage(): void;\n"},
            {"path": "src/index.css", "content": "html, body, #root { min-height: 100%; margin: 0; }\n"}]
