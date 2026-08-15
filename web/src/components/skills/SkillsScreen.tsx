import { useEffect, useState } from "react";

import {
  fetchSkill,
  fetchSkillVersion,
  fetchSkillVersions,
  fetchSkills,
  recordSkillRun,
  revertSkillVersion,
  type SkillDetail,
  type SkillEvaluationOut,
  type SkillSummary,
  type SkillVersionOut,
} from "../../lib/api";

function qualityDot(status: string): string {
  return `skills__dot skills__dot--${status === "active" ? "active" : status === "deprecated" ? "deprecated" : "draft"}`;
}

function statusLabel(status: string): string {
  if (status === "active") return "active";
  if (status === "deprecated") return "deprecated";
  return "draft";
}

function purposeShort(purpose: string): string {
  if (purpose.length <= 180) return purpose;
  return `${purpose.slice(0, 180)}…`;
}

export default function SkillsScreen({ onHome }: { onHome: () => void }) {
  const [skills, setSkills] = useState<SkillSummary[] | null>(null);
  const [active, setActive] = useState<SkillDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSkills()
      .then((list) => setSkills(list))
      .catch((err) => setError(`skills did not load: ${err}`));
  }, []);

  const openSkill = (skillId: string) => {
    setActive(null);
    fetchSkill(skillId, true)
      .then(setActive)
      .catch((err) => setError(`skill did not load: ${err}`));
  };

  const close = () => {
    setActive(null);
    onHome();
  };

  return (
    <div className="skills">
      <header className="skills__header">
        <button className="skills__back" type="button" onClick={close}>
          ← home
        </button>
        <h1 className="skills__title">Her shelf</h1>
        <p className="skills__subtitle">Skills she wrote for herself — pages with a spine, and how they prove out.</p>
      </header>

      {error && <div className="skills__error">{error}</div>}

      {active ? (
        <SkillDetailView
          skill={active}
          onRefresh={() => openSkill(active.id)}
          onBack={() => setActive(null)}
        />
      ) : (
        <div className="skills__grid">
          {skills === null && !error && <div className="skills__loading" aria-label="loading" />}
          {(skills ?? []).map((s) => (
            <button
              key={`${s.category}/${s.id}`}
              className="skills__card"
              type="button"
              onClick={() => openSkill(s.id)}
            >
              <div className="skills__card-head">
                <span className={qualityDot(s.status)} />
                <span className="skills__card-id">{s.category}/{s.id}</span>
                <span className="skills__version">v{s.version}</span>
              </div>
              <div className="skills__card-status">{statusLabel(s.status)}</div>
              {s.purpose && <p className="skills__card-purpose">{purposeShort(s.purpose)}</p>}
              <div className="skills__card-foot">
                <span>{s.tools.length ? s.tools.join(" · ") : "no tools yet"}</span>
                <span>
                  {s.run_count != null ? `${s.run_count} run${s.run_count === 1 ? "" : "s"}` : "no runs"}
                  {s.last_edited ? ` · changed ${new Date(s.last_edited).toLocaleDateString()}` : ""}
                  {" · "}
                  {s.verification.length} checks
                </span>
              </div>
            </button>
          ))}
          {skills !== null && skills.length === 0 && (
            <p className="skills__empty">The shelf is empty — she has not written a skill yet.</p>
          )}
        </div>
      )}
    </div>
  );
}

function SkillDetailView({ skill, onBack, onRefresh }: { skill: SkillDetail; onBack: () => void; onRefresh: () => void }) {
  const lastEval = skill.recent_evaluations[0];
  const scores = (lastEval?.scores ?? {}) as Record<string, number | Record<string, unknown>>;
  const overall = typeof scores.overall === "number" ? scores.overall : null;
  const dims = (scores.dimensions ?? {}) as Record<string, number>;

  return (
    <div className="skills__detail">
      <div className="skills__detail-head">
        <button className="skills__back" type="button" onClick={onBack}>
          ← shelf
        </button>
        <div className="skills__detail-title">
          <span className={qualityDot(skill.status)} />
          <h2>{skill.category}/{skill.id}</h2>
          <span className="skills__version">v{skill.version} · {statusLabel(skill.status)}</span>
        </div>
      </div>

      {skill.purpose && <p className="skills__detail-purpose">{skill.purpose}</p>}

      <div className="skills__detail-cols">
        <section className="skills__section">
          <h3>What it uses</h3>
          <ul className="skills__list">
            {skill.tools.length
              ? skill.tools.map((t) => <li key={t}>{t}</li>)
              : <li>nothing yet</li>}
          </ul>
        </section>

        <section className="skills__section">
          <h3>How it is verified</h3>
          <ul className="skills__list">
            {skill.verification.length
              ? skill.verification.map((v) => <li key={v}>{v}</li>)
              : <li>no checks declared</li>}
          </ul>
        </section>

        <section className="skills__section">
          <h3>Where it fails</h3>
          <ul className="skills__list">
            {skill.failure_modes.length
              ? skill.failure_modes.map((f) => <li key={f}>{f}</li>)
              : <li>not written down yet</li>}
          </ul>
        </section>

        <section className="skills__section">
          <h3>Its lines</h3>
          <ul className="skills__list">
            {skill.constraints.length
              ? skill.constraints.map((c) => <li key={c}>{c}</li>)
              : <li>none declared</li>}
          </ul>
        </section>
      </div>

      <section className="skills__section">
        <h3>Provenance</h3>
        {overall != null ? (
          <div>
            <span className="skills__score" title={`overall ${overall.toFixed(2)}`}>
              {overall.toFixed(2)}
            </span>
            <div className="skills__dims">
              {Object.entries(dims).map(([k, v]) => (
                <span key={k} className="skills__dim">
                  {k}: <strong>{typeof v === "number" ? v.toFixed(2) : "—"}</strong>
                </span>
              ))}
            </div>
          </div>
        ) : (
          <p className="skills__muted">No evaluations yet — she has not run it with the checks on.</p>
        )}
        {lastEval && (
          <p className="skills__muted">Last run ({skill.recent_runs[0]?.created_at?.slice(0, 10) ?? "recorded"}): {lastEval.task}</p>
        )}
      </section>

      <section className="skills__section">
        <h3>Runs</h3>
        {skill.recent_runs.length ? (
          <ul className="skills__runs">
            {skill.recent_runs.map((r) => (
              <li key={r.id} className={`skills__run skills__run--${r.status}`}>
                <span className="skills__run-task">{r.task}</span>
                <span className="skills__run-status">{r.status}</span>
                {r.error && <span className="skills__run-error">{r.error.slice(0, 140)}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="skills__muted">No runs recorded yet.</p>
        )}
      </section>

      <RunAndProve skill={skill} onEvaluated={onRefresh} />

      <GrowthHistory skill={skill} onRefreshed={onRefresh} />

      {skill.page && (
        <section className="skills__section">
          <h3>The page, as she wrote it</h3>
          <pre className="skills__page">{skill.page}</pre>
        </section>
      )}
    </div>
  );
}

function RunAndProve({ skill, onEvaluated }: { skill: SkillDetail; onEvaluated: () => void }) {
  const [task, setTask] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SkillEvaluationOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (!task.trim()) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await recordSkillRun(skill.id, { task, output });
      if (res.evaluation) {
        setResult(res.evaluation);
        onEvaluated(); // refresh the detail so the ledger shows the new run
      } else {
        setError("This skill declares no checks yet, so it ran without a score.");
      }
    } catch (err) {
      setError(`run failed: ${err}`);
    } finally {
      setBusy(false);
    }
  };

  const score = result?.scores ?? {};
  const overall = typeof score.overall === "number" ? score.overall : null;
  const checks = (score.checks ?? {}) as Record<string, unknown>;

  return (
    <section className="skills__section">
      <h3>Run it, and prove it</h3>
      <p className="skills__muted">
        Record what she was asked and what she brought back; the shelf scores it
        against this skill's own checks.
      </p>
      <input
        className="skills__input"
        type="text"
        placeholder="What was she asked?"
        value={task}
        onChange={(e) => setTask(e.target.value)}
      />
      <textarea
        className="skills__textarea"
        placeholder="What did she bring back? (papers, titles, findings…)"
        value={output}
        onChange={(e) => setOutput(e.target.value)}
      />
      <button className="skills__cta" type="button" onClick={run} disabled={busy || !task.trim()}>
        {busy ? "recording…" : "Record a run + score it"}
      </button>
      {error && <div className="skills__error">{error}</div>}
      {result && overall != null && (
        <div className="skills__result">
          <span className="skills__score" title={`overall ${overall.toFixed(2)}`}>
            {overall.toFixed(2)}
          </span>
          <ul className="skills__list">
            {Object.entries(checks).map(([k, v]) => (
              <li key={k}>
                {k}: <strong>{v === true ? "passed" : v === false ? "failed" : String(v)}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function GrowthHistory({ skill, onRefreshed }: { skill: SkillDetail; onRefreshed: () => void }) {
  const [versions, setVersions] = useState<SkillVersionOut[] | null>(null);
  const [open, setOpen] = useState<SkillVersionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setVersions(null);
    setOpen(null);
    fetchSkillVersions(skill.id, skill.category)
      .then(setVersions)
      .catch((err) => setError(`version history did not load: ${err}`));
  }, [skill.id, skill.category]);

  const expand = async (v: SkillVersionOut) => {
    if (open?.id === v.id) {
      setOpen(null);
      return;
    }
    setOpen(null);
    fetchSkillVersion(skill.id, v.id, skill.category)
      .then(setOpen)
      .catch((err) => setError(`version did not load: ${err}`));
  };

  const revert = async (v: SkillVersionOut) => {
    if (!window.confirm(`Put ${v.path} back to how it was before "edit #${v.id}"?`)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await revertSkillVersion(skill.id, v.id, skill.category);
      setNotice(`Reverted to before edit #${v.id}.`);
      onRefreshed();
    } catch (err) {
      setError(`revert failed: ${err}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="skills__section">
      <h3>How it has changed</h3>
      <p className="skills__muted">
        Every edit to her own files is pinned here — look at the change, and
        put it back if it made the skill worse.
      </p>
      {error && <div className="skills__error">{error}</div>}
      {notice && <div className="skills__notice">{notice}</div>}
      {versions === null && !error && <div className="skills__loading" aria-label="loading" />}
      {versions && versions.length === 0 && (
        <p className="skills__muted">No edits recorded yet — she has not changed her own files.</p>
      )}
      {versions && versions.length > 0 && (
        <ul className="skills__versions">
          {versions.map((v) => (
            <li key={v.id} className={`skills__version skills__version--${v.kind}`}>
              <button className="skills__version-toggle" type="button" onClick={() => expand(v)}>
                <span className="skills__version-kind">
                  {v.kind === "revert" ? "reverted" : "edit"}
                </span>
                <span className="skills__version-reason">{v.reason || v.path}</span>
                <span className="skills__version-path">{v.path}</span>
                <span className="skills__version-date">
                  {v.created_at?.slice(0, 10) ?? "—"} · {v.created_at?.slice(11, 16) ?? ""}
                </span>
              </button>
              {v.kind !== "revert" && (
                <button
                  className="skills__revert"
                  type="button"
                  onClick={() => revert(v)}
                  disabled={busy}
                >
                  revert
                </button>
              )}
              {open?.id === v.id && (
                <pre className="skills__diff">
                  {open.diff?.map((d, i) => (
                    <code key={i} className={`skills__diff-line skills__diff-line--${d.tag}`}>
                      {d.tag === "removed" ? "− " : "+ "}
                      {d.line}
                    </code>
                  ))}
                </pre>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
