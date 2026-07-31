"use client";
// Settings (PRD §21): profile (name drives the Home greeting), preferred currency
// and language, net-worth preferences, and JSON backup export/import (PRD §2.1).
import { useEffect, useRef, useState } from "react";
import { CURRENCIES } from "../lib/format";
import { getSettings, putSettings, exportBackup, importBackup } from "../lib/api";
import { Field, TextInput, Select, Button } from "../components/ui";

const TOGGLES = [
  { key: "include_debts", label: "Include debts in net worth" },
  { key: "include_receivables", label: "Include receivables in net worth" },
  { key: "include_credit", label: "Include credit card debt in wallet" },
  { key: "show_decimals", label: "Show decimals" },
];

export default function SettingsPage() {
  const [s, setS] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSettings().then((v) => {
      setS(v);
      if (v.profile_name) localStorage.setItem("profile-name", v.profile_name);
    }).catch(() => {});
  }, []);

  const set = (k: string, v: string) => setS((prev) => ({ ...prev, [k]: v }));
  const bool = (k: string) => s[k] === "true" || s[k] === "1";

  const save = async () => {
    const next = await putSettings(s);
    setS(next);
    localStorage.setItem("profile-name", next.profile_name || "");
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  const doExport = async () => {
    const data = await exportBackup();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ledger-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const doImport = async (file: File) => {
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      // Import with replace clears every finance table first, so the records
      // currently in the ledger are gone for good unless they were exported. That
      // is not something to do on a stray click on a file picker.
      const ok = window.confirm(
        "Import will REPLACE everything currently in your ledger — accounts, " +
          "transactions, budgets, goals, debts — with the contents of this file.\n\n" +
          "Export a backup first if you have not. Continue?",
      );
      if (!ok) {
        setMsg("Import cancelled. Nothing was changed.");
        return;
      }
      const res = await importBackup({ ...payload, replace: true });
      const n = Object.values(res.imported || {}).reduce((s: number, x: any) => s + x, 0);
      setMsg(`Imported ${n} records. Reloading…`);
      setTimeout(() => window.location.reload(), 1200);
    } catch (e: any) {
      setMsg(`Import failed: ${e.message}`);
    }
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Settings</h1>
            <p className="subhead">Profile, preferences, and your data</p>
          </div>
          <button className="btn-primary" onClick={save}>{saved ? "Saved ✓" : "Save changes"}</button>
        </header>

        <div className="grid-2">
          <div className="card">
            <p className="section-title">Profile</p>
            <div className="inline-form">
              <Field label="Preferred name" hint="Shown in your dashboard greeting">
                <TextInput placeholder="e.g. Bryl" value={s.profile_name || ""} onChange={(e) => set("profile_name", e.target.value)} />
              </Field>
              <div className="field-row">
                <Field label="Preferred currency">
                  <Select value={s.currency || "PHP"} onChange={(e) => set("currency", e.target.value)}>
                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </Select>
                </Field>
                <Field label="Language">
                  <Select value={s.language || "English"} onChange={(e) => set("language", e.target.value)}>
                    <option value="English">English</option>
                    <option value="Filipino">Filipino</option>
                  </Select>
                </Field>
              </div>
            </div>
          </div>

          <div className="card">
            <p className="section-title">Net worth preferences</p>
            <div className="inline-form">
              {TOGGLES.map((t) => (
                <label key={t.key} className="check-row">
                  <input type="checkbox" checked={bool(t.key)} onChange={(e) => set(t.key, e.target.checked ? "true" : "false")} />
                  {t.label}
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <p className="section-title">Your data</p>
          <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--ink-2)" }}>
            Edit preferences here, then keep them in your next downloaded backup. Export saves everything to a JSON file; import replaces the current session with a backup.
          </p>
          {msg && <div className="form-error" style={{ marginBottom: 12 }}>{msg}</div>}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Button variant="primary" onClick={doExport}>Export data</Button>
            <Button onClick={() => fileRef.current?.click()}>Import backup</Button>
            <input ref={fileRef} type="file" accept="application/json" style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                // Clear the input so picking the same file again re-fires onChange —
                // otherwise cancelling the confirm below would make that file unpickable.
                e.target.value = "";
                if (file) doImport(file);
              }} />
          </div>
        </div>
      </main>
    </>
  );
}
