"use client";
// Plan > Categories (PRD §8): two panels for inline creation of categories and
// subcategories. Only custom categories can be deleted; system defaults cannot.
import { useCallback, useEffect, useState } from "react";
import type { TxnCategory } from "../../lib/types";
import { listCategories, createCategory, deleteCategory } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, FormError, ColorPicker } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function CategoriesPage() {
  const [cats, setCats] = useState<TxnCategory[]>([]);
  const load = useCallback(() => {
    listCategories().then(setCats).catch(() => setCats([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const parents = cats.filter((c) => c.parent_id == null);
  const subs = cats.filter((c) => c.parent_id != null);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Categories</h1>
            <p className="subhead">Organize income and expenses</p>
          </div>
        </header>

        <div className="band">
          <CategoryPanel
            title="Categories"
            parents={parents}
            onCreate={(name, kind, color) => createCategory({ name, kind, color })}
            onReload={load}
            rows={parents}
            catName={() => null}
          />
          <CategoryPanel
            title="Subcategories"
            parents={parents}
            withParent
            onCreate={(name, kind, color, parentId) => createCategory({ name, kind, color, parent_id: parentId })}
            onReload={load}
            rows={subs}
            catName={(id) => parents.find((p) => p.id === id)?.name || null}
          />
        </div>
      </main>
    </>
  );
}

function CategoryPanel({
  title,
  parents,
  withParent,
  onCreate,
  onReload,
  rows,
  catName,
}: {
  title: string;
  parents: TxnCategory[];
  withParent?: boolean;
  onCreate: (name: string, kind: "expense" | "income", color: string, parentId?: number) => Promise<any>;
  onReload: () => void;
  rows: TxnCategory[];
  catName: (parentId: number) => string | null;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [color, setColor] = useState("#6366F1");
  const [parentId, setParentId] = useState(parents[0]?.id ?? 0);
  const [err, setErr] = useState<string | null>(null);

  const add = async () => {
    if (!name.trim()) return setErr("Name is required");
    setErr(null);
    try {
      await onCreate(name.trim(), kind, color, withParent ? parentId : undefined);
      setName("");
      onReload();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const remove = async (c: TxnCategory) => {
    try {
      await deleteCategory(c.id);
      onReload();
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="card">
      <p className="section-title">{title}</p>
      <FormError message={err} />
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
        <Field label="Name">
          <TextInput placeholder="e.g. Coffee" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Kind">
          <Select value={kind} onChange={(e) => setKind(e.target.value as any)}>
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </Select>
        </Field>
        <Field label="Color">
          <ColorPicker value={color} onChange={setColor} />
        </Field>
        {withParent && (
          <Field label="Parent">
            <Select value={parentId} onChange={(e) => setParentId(Number(e.target.value))}>
              {parents.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </Field>
        )}
        <Button variant="primary" onClick={add}>Add {withParent ? "subcategory" : "category"}</Button>
      </div>

      <div>
        {rows.length === 0 ? (
          <EmptyState
            size="panel"
            glyphs={["tag", "chart", "receipt"]}
            title="None yet"
            sub="Categories sort your spending automatically."
          />
        ) : (
          rows.map((c) => (
            <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "1px solid var(--border)" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", background: c.color || "var(--ink-3)" }} />
              <span style={{ flex: 1, fontSize: 13.5, fontWeight: 500 }}>
                {c.name}
                {withParent && catName(c.parent_id!) && (
                  <span style={{ color: "var(--ink-3)", fontWeight: 400 }}> · {catName(c.parent_id!)}</span>
                )}
              </span>
              <span className="cat-pill">{c.kind}</span>
              {!c.is_system ? (
                <button className="mini-btn danger" onClick={() => remove(c)}>Delete</button>
              ) : (
                <span style={{ fontSize: 11, color: "var(--ink-3)" }}>system</span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
