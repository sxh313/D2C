import { useRef, useEffect } from "react";
import { Compartment, EditorState, Transaction } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, ViewUpdate } from "@codemirror/view";
import { espresso, cobalt } from "thememirror";
import {
  defaultKeymap,
  history,
  indentWithTab,
  redo,
  undo,
} from "@codemirror/commands";
import { bracketMatching } from "@codemirror/language";
import { html } from "@codemirror/lang-html";
import { EditorTheme } from "@/types";

interface Props {
  code: string;
  editorTheme: EditorTheme;
  onCodeChange: (code: string) => void;
  readOnly?: boolean;
  language?: "html" | "text";
  label?: string;
  className?: string;
}

function CodeMirror({ code, editorTheme, onCodeChange, readOnly = false, language = "html", label = "代码编辑器", className }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onCodeChangeRef = useRef(onCodeChange);
  onCodeChangeRef.current = onCodeChange;
  const initialCode = useRef(code);
  const initialTheme = useRef(editorTheme);
  const theme = useRef(new Compartment());
  const editing = useRef(new Compartment());
  const syntax = useRef(new Compartment());
  const accessibility = useRef(new Compartment());

  useEffect(() => {
    const editorState = EditorState.create({
      doc: initialCode.current,
      extensions: [
        history(),
        keymap.of([
          ...defaultKeymap,
          indentWithTab,
          { key: "Mod-z", run: undo, preventDefault: true },
          { key: "Mod-Shift-z", run: redo, preventDefault: true },
        ]),
        lineNumbers(),
        bracketMatching(),
        syntax.current.of([]),
        editing.current.of([]),
        accessibility.current.of([]),
        theme.current.of(initialTheme.current === EditorTheme.ESPRESSO ? espresso : cobalt),
        EditorView.lineWrapping,
        EditorView.updateListener.of((update: ViewUpdate) => {
          if (update.docChanged && update.transactions.some((transaction) => !transaction.annotation(Transaction.remote))) {
            onCodeChangeRef.current(update.state.doc.toString());
          }
        }),
      ],
    });
    const editor = new EditorView({ state: editorState, parent: ref.current as Element });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, []);

  useEffect(() => {
    view.current?.dispatch({
      effects: theme.current.reconfigure(editorTheme === EditorTheme.ESPRESSO ? espresso : cobalt),
    });
  }, [editorTheme]);

  useEffect(() => {
    view.current?.dispatch({ effects: [
      editing.current.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
      syntax.current.reconfigure(language === "html" ? html() : []),
      accessibility.current.reconfigure(EditorView.contentAttributes.of({ "aria-label": label, "aria-readonly": String(readOnly) })),
    ] });
  }, [readOnly, language, label]);

  useEffect(() => {
    if (view.current && view.current.state.doc.toString() !== code) {
      view.current.dispatch({
        changes: { from: 0, to: view.current.state.doc.length, insert: code },
        annotations: Transaction.remote.of(true),
      });
    }
  }, [code]);

  return (
    <div
      className={className || "overflow-x-scroll overflow-y-scroll mx-2 border-[4px] border-black rounded-[20px]"}
      ref={ref}
    />
  );
}

export default CodeMirror;
