import { useState } from 'react';
import { postJson } from '../api';

export default function ProfileCreationScreen({ initialUser, onComplete }) {
  const [form, setForm] = useState({
    name: initialUser?.name || '',
    department: initialUser?.department || '',
    role: initialUser?.role || '',
    experience_years: initialUser?.experience_years ?? 0,
    skills: initialUser?.skills?.join(', ') || '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const update = (field) => (e) => setForm((s) => ({ ...s, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      const skills = form.skills
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const payload = {
        ...form,
        experience_years: Number(form.experience_years) || 0,
        skills,
      };
      const data = await postJson('/api/user/profile', payload);
      onComplete(data.profile);
    } catch (err) {
      setError(err.message || 'Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="si-profile-root">
      <header className="si-profile-header">
        <div className="si-profile-header-brand">
          <div className="si-profile-header-logo">S</div>
          <span>SIEMENS Workforce Intelligence</span>
        </div>
      </header>

      <main className="si-profile-body">
        <div className="si-profile-card">
          <h2 className="si-profile-title">Complete Your Profile</h2>
          <p className="si-profile-subtitle">
            Signed in as <strong>{initialUser?.email}</strong>. Add your professional details to personalize the workspace.
          </p>

          {error && <div className="si-login-error" style={{ marginBottom: 14 }}>{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="si-profile-row">
              <label className="si-profile-row-label" htmlFor="profile-name">Full Name</label>
              <input
                id="profile-name"
                className="si-profile-input"
                type="text"
                value={form.name}
                onChange={update('name')}
                placeholder="e.g. Jane Smith"
              />
            </div>

            <div className="si-profile-row">
              <label className="si-profile-row-label" htmlFor="profile-dept">Department</label>
              <input
                id="profile-dept"
                className="si-profile-input"
                type="text"
                value={form.department}
                onChange={update('department')}
                placeholder="e.g. Digital Industries"
              />
            </div>

            <div className="si-profile-row">
              <label className="si-profile-row-label" htmlFor="profile-role">Current Role</label>
              <input
                id="profile-role"
                className="si-profile-input"
                type="text"
                value={form.role}
                onChange={update('role')}
                placeholder="e.g. Senior Software Engineer"
              />
            </div>

            <div className="si-profile-row">
              <label className="si-profile-row-label" htmlFor="profile-exp">Years of Experience</label>
              <input
                id="profile-exp"
                className="si-profile-input"
                type="number"
                min="0"
                max="50"
                value={form.experience_years}
                onChange={update('experience_years')}
              />
            </div>

            <div className="si-profile-row">
              <label className="si-profile-row-label" htmlFor="profile-skills">Skills (comma separated)</label>
              <textarea
                id="profile-skills"
                className="si-profile-textarea"
                value={form.skills}
                onChange={update('skills')}
                placeholder="Python, Kubernetes, React, AWS..."
              />
            </div>

            <div className="si-profile-actions">
              <button type="submit" className="si-profile-btn-primary" disabled={saving}>
                {saving ? 'Saving…' : 'Save Profile'}
              </button>
              <button
                type="button"
                className="si-profile-btn-secondary"
                disabled={saving}
                onClick={() => onComplete(initialUser)}
              >
                Skip for now
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}
