"use client";
// Plan > Tags (PRD §9): lightweight tagging with inline creation.
import { useCallback, useEffect, useState } from "react";
import type { Tag } from "../../lib/types";
import { listTags, createTag, deleteTag } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, FormError, ColorPicker } from "../../components/ui";

export default function TagsPage() {
  const [tags, setTags] = useState<Tag[]>([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("Custom");
  const [color, setColor] = useState("#14B8A6");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    listTags().then(setTags).catch(() => setTags([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const add = async () => {
    if (!name.trim()) return setErr("Name is required");
    setErr(null);
    try {
      await createTag({ name: name.trim(), kind, color });
      setName("");
      load();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Tags</h1>
            <p className="subhead">Label transactions across categories</p>
          </div>
        </header>

        <div className="card" style={{ maxWidth: 520 }}>
          <FormError message={err} />
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
            <Field label="Name">
              <TextInput placeholder="e.g. Japan trip" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Kind">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="Custom">Custom</option>
                <option value="Trip">Trip</option>
              </Select>
            </Field>
            <Field label="Color">
              <ColorPicker value={color} onChange={setColor} />
            </Field>
            <Button variant="primary" onClick={add}>Add tag</Button>
          </div>

          {tags.length === 0 ? (
            <div className="empty-note">No tags yet.</div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {tags.map((t) => (
                <span key={t.id} className="acct-type-pill" style={{ background: t.color || "var(--ink-3)", display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {t.name}
                  <button onClick={() => deleteTag(t.id).then(load)} style={{ background: "none", border: "none", color: "#fff", opacity: 0.8, padding: 0 }} aria-label="Delete tag">×</button>
                </span>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
