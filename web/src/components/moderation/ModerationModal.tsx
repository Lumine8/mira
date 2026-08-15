import { useEffect, useState } from "react";

import {
  banFromFlag,
  banUser,
  deleteUser,
  dismissFlag,
  fetchModerationFlags,
  fetchModerationUsers,
  unbanUser,
  waitlistDecline,
  waitlistForget,
  waitlistInvite,
  waitlistList,
} from "../../lib/api";
import type { ModerationFlag, ModerationUser, WaitlistEntry } from "../../lib/types";

interface ModerationModalProps {
  open: boolean;
  onClose: () => void;
}

export default function ModerationModal({ open, onClose }: ModerationModalProps) {
  const [flags, setFlags] = useState<ModerationFlag[]>([]);
  const [users, setUsers] = useState<ModerationUser[]>([]);
  const [waitlist, setWaitlist] = useState<WaitlistEntry[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [lastCode, setLastCode] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void fetchModerationFlags().then(setFlags);
    void fetchModerationUsers().then(setUsers);
    void waitlistList().then(setWaitlist);
  }, [open]);

  if (!open) return null;

  const banFlag = async (flagId: number, reason = "") => {
    try {
      await banFromFlag(flagId, reason);
      setFlags((prev) => prev.filter((f) => f.id !== flagId));
    } catch (err) {
      setNotice(`Could not ban: ${err instanceof Error ? err.message : err}`);
    }
  };

  const dismiss = async (flagId: number) => {
    try {
      await dismissFlag(flagId);
      setFlags((prev) => prev.filter((f) => f.id !== flagId));
    } catch (err) {
      setNotice(`Could not dismiss: ${err instanceof Error ? err.message : err}`);
    }
  };

  const ban = async (userId: number) => {
    try {
      await banUser(userId);
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, status: "banned" } : u)));
    } catch (err) {
      setNotice(`Could not ban: ${err instanceof Error ? err.message : err}`);
    }
  };

  const unban = async (userId: number) => {
    try {
      await unbanUser(userId);
      setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, status: "active" } : u)));
    } catch (err) {
      setNotice(`Could not unban: ${err instanceof Error ? err.message : err}`);
    }
  };

  const remove = async (userId: number) => {
    try {
      await deleteUser(userId);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch (err) {
      setNotice(`Could not delete that world: ${err instanceof Error ? err.message : err}`);
    }
  };

  const invite = async () => {
    const email = inviteEmail.trim();
    if (!email) return;
    try {
      const resp = await waitlistInvite(email);
      setLastCode(resp.invite_code);
      setInviteEmail("");
      void waitlistList().then(setWaitlist);
      if (resp.delivered) {
        setNotice(`Invitation emailed to ${email}.`);
      } else {
        const subject = "A place to enter";
        const body =
          "The voice told me you were coming, and I've been keeping a spot open for you.\n\n" +
          `Your invite code is ${resp.invite_code}.\n\n` +
          "I look forward to meeting you.\n\n— Mira";
        window.location.href = `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
        setNotice(`Opened your mail — the invitation for ${email} is waiting to send.`);
      }
    } catch (err) {
      setNotice(`Could not invite that address: ${err instanceof Error ? err.message : err}`);
    }
  };

  const decline = async (entryId: number) => {
    try {
      await waitlistDecline(entryId);
      setWaitlist((prev) => prev.filter((e) => e.id !== entryId));
    } catch (err) {
      setNotice(`Could not close that door: ${err instanceof Error ? err.message : err}`);
    }
  };

  const forget = async (entryId: number, email: string) => {
    if (!window.confirm(`Forget ${email}? The seat is erased and they can ask again.`)) return;
    try {
      await waitlistForget(entryId);
      setWaitlist((prev) => prev.filter((e) => e.id !== entryId));
      setNotice(`Forgot ${email}.`);
    } catch (err) {
      setNotice(`Could not forget that seat: ${err instanceof Error ? err.message : err}`);
    }
  };

  return (
    <div className="moderation" role="dialog" aria-modal="true">
      <div className="moderation__card">
        <div className="moderation__head">
          <h3 className="moderation__title">The door</h3>
          <button className="moderation__close" type="button" onClick={onClose} aria-label="close moderation">
            ×
          </button>
        </div>

        {notice && <p className="moderation__notice">{notice}</p>}

        <section className="moderation__section">
          <h4 className="moderation__label">At the door</h4>
          {lastCode ? (
            <p className="moderation__code">
              Invitation code for <strong>{lastCode}</strong> — share it with them.
            </p>
          ) : null}
          <div className="moderation__invite">
            <input
              className="moderation__input"
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="email to invite"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") invite();
              }}
            />
            <button className="moderation__button" type="button" onClick={invite}>
              Invite
            </button>
          </div>
          {waitlist.length === 0 ? (
            <p className="moderation__empty">Nobody waiting.</p>
          ) : (
            <ul className="moderation__list">
              {waitlist.map((entry) => (
                <li key={entry.id} className="moderation__row">
                  <div className="moderation__row-main">
                    <span className="moderation__row-name">{entry.email}</span>
                    <span className="moderation__row-status">{entry.status}</span>
                  </div>
                  <div className="moderation__row-actions">
                    <button className="moderation__button" type="button" onClick={() => forget(entry.id, entry.email)}>
                      Forget
                    </button>
                    <button className="moderation__button moderation__button--danger" type="button" onClick={() => decline(entry.id)}>
                      Close
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="moderation__section">
          <h4 className="moderation__label">Flagged — your call</h4>
          {flags.length === 0 ? (
            <p className="moderation__empty">Nothing flagged.</p>
          ) : (
            <ul className="moderation__list">
              {flags.map((flag) => (
                <li key={flag.id} className="moderation__foot">
                  <div className="moderation__foot-body">
                    <span className="moderation__row-name">{flag.user_name}</span>
                    <p className="moderation__foot-text">{flag.content}</p>
                  </div>
                  <div className="moderation__foot-actions">
                    <button className="moderation__button" type="button" onClick={() => dismiss(flag.id)}>
                      Dismiss
                    </button>
                    <button className="moderation__button moderation__button--danger" type="button" onClick={() => banFlag(flag.id, flag.reason)}>
                      Ban
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="moderation__section">
          <h4 className="moderation__label">The house</h4>
          {users.length === 0 ? (
            <p className="moderation__empty">No one in the house yet.</p>
          ) : (
            <ul className="moderation__list">
              {users.map((user) => (
                <li key={user.id} className="moderation__row">
                  <div className="moderation__row-main">
                    <span className="moderation__row-name">{user.name}</span>
                    <span className="moderation__row-status">
                      {user.role} · {user.status}
                    </span>
                  </div>
                  <div className="moderation__row-actions">
                    {user.status === "banned" ? (
                      <button className="moderation__button" type="button" onClick={() => unban(user.id)}>
                        Unban
                      </button>
                    ) : (
                      user.role !== "founder" && (
                        <>
                          <button className="moderation__button" type="button" onClick={() => ban(user.id)}>
                            Ban
                          </button>
                          <button className="moderation__button moderation__button--danger" type="button" onClick={() => remove(user.id)}>
                            Forget
                          </button>
                        </>
                      )
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}