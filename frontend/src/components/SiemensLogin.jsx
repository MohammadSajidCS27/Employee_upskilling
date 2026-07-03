import { useState } from 'react';
import { postJson } from '../api';

export default function SiemensLoginScreen({ onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!email.trim()) {
      setError('Please enter an email address');
      return;
    }
    setLoading(true);
    try {
      await onLogin({ email: email.trim(), password });
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="main-layout">
      <div className="prompt-wrapper">
        <div className="siemens-navbar">
          <div className="siemens-navbar-content">
            <div className="siemens-navbar-logo">
              <a href="https://www.siemens.com/" target="_blank" rel="noreferrer">
                <img 
                  src="https://cdn.login.siemens.com/public/logo/white/sie-logo-white-rgb.svg" 
                  alt="Siemens Logo" 
                  width="126.25px" 
                  height="20px" 
                />
              </a>
            </div>
            <div className="siemens-navbar-links">
              <ul>
                <li><a href="https://sp.login.siemens.com/" target="_blank" rel="noreferrer">Service Portal</a></li>
                <li><a href="https://id.login.siemens.com/" target="_blank" rel="noreferrer">Help</a></li>
              </ul>
            </div>
          </div>
        </div>

        <main className="_widget login-id">
          <section className="c5431f316 _prompt-box-outer ca8ae2309">
            <div className="cea408cbe c3294138f">
              <div className="c6cde4daa">
                <header className="ca43254f0 c499f492f" id="screen-header" tabIndex="-1">
                  <div 
                    title="Siemens ID" 
                    id="custom-prompt-logo" 
                    style={{
                      width: 'auto !important', 
                      height: '60px !important', 
                      position: 'static !important', 
                      margin: 'auto !important', 
                      padding: '0 !important', 
                      backgroundColor: 'transparent !important', 
                      backgroundPosition: 'center !important', 
                      backgroundSize: 'contain !important', 
                      backgroundRepeat: 'no-repeat !important'
                    }}
                  />
                  <img 
                    className="c7bbeb26c ca2220b5a" 
                    id="prompt-logo-center" 
                    src="https://cdn.login.siemens.com/public/images/sie-logo-white-rgb-mfa.svg" 
                    alt="Siemens ID" 
                  />
                  <h1 className="cba8df1ce c9b7c85f1">Log in</h1>
                  <div className="cddf422f5 cbdcf07fd">
                    <p className="c5ff91828 c4ff0973c">Sign in to your account</p>
                  </div>
                </header>

                <div className="c5b9cb0cf c56e48ef2">
                  <div className="cc4069bbe cc22a6267">
                    <div className="c4402ca7c">
                      <form 
                        method="POST" 
                        className="c583c0a13 _form-login-id" 
                        data-form-primary="true" 
                        data-disable-html-validations="true"
                        onSubmit={handleSubmit}
                      >
                        <div id="ulp-error-announcer" className="screen-reader-only" aria-live="assertive" aria-atomic="true" />
                        
                        <input 
                          type="hidden" 
                          name="state" 
                          value="hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8" 
                        />
                        
                        <div className="input-wrapper _input-wrapper">
                          <div className="cb4eb055c c48f044e7 text cb62648e6 ulp-field">
                            <label id="username-label" className="cb1ce033b ce3dd32dd c019efb25" htmlFor="username">
                              Email address
                              <span className="required" aria-hidden="true">*</span>
                            </label>
                            <input 
                              className="input c2b8d38fa cc829e2ad" 
                              inputMode="email" 
                              name="username" 
                              id="username" 
                              type="text" 
                              aria-labelledby="username-label" 
                              aria-required="true" 
                              value={email} 
                              onChange={(e) => setEmail(e.target.value)}
                              required 
                              autoComplete="email" 
                              autoCapitalize="none" 
                              spellCheck="false" 
                            />
                          </div>
                          <div id="error-cs-username-required" className="ulp-error-info aria-error-check" style={{ display: 'none' }}>
                            Please enter an email address
                          </div>
                          <div id="error-cs-email-invalid" className="ulp-error-info aria-error-check" style={{ display: 'none' }}>
                            Email is not valid.
                          </div>
                          <div id="error-cs-pattern-mismatch" className="ulp-error-info aria-error-check" style={{ display: 'none' }} />
                          {error && (
                            <div className="ulp-error-info" style={{ display: 'block', color: '#FF7687' }}>
                              {error}
                            </div>
                          )}
                        </div>

                        <input className="hide" type="password" autoComplete="off" tabIndex="-1" aria-hidden="true" />

                        <input type="hidden" id="js-available" name="js-available" value="false" />
                        <input type="hidden" id="webauthn-available" name="webauthn-available" value="false" />
                        <input type="hidden" id="is-brave" name="is-brave" value="false" />
                        <input type="hidden" id="webauthn-platform-available" name="webauthn-platform-available" value="false" />

                        <div className="c854fadc6">
                          <button 
                            type="submit" 
                            name="action" 
                            value="default" 
                            className="cc9c37347 ccfae5bcb ce0a9fe30 cf9a2ed2e _button-login-id" 
                            data-action-button-primary="true"
                            disabled={loading}
                          >
                            {loading ? 'Signing in…' : 'Continue'}
                          </button>
                        </div>
                      </form>
                    </div>
                  </div>
                </div>

                <div id="ulp-container-form-footer-start" />

                <div className="ulp-alternate-action _alternate-action __s16nu9">
                  <p className="c5ff91828 c4ff0973c ce2e12ef9">
                    Don't have an account?{' '}
                    <a className="c41cc1129 caabfe509" href="/u/signup/identifier?state=hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8">
                      Create one
                    </a>
                  </p>
                </div>

                <div id="ulp-container-form-footer-end" />

                <div className="c357271f4 cfc3ebfc3">
                  <span>Or</span>
                </div>

                <div className="cb38313b0 ceebe3fc8">
                  <div id="ulp-container-secondary-actions-start" />

                  <form method="post" data-provider="google" className="c17ed0264 cb2f06e4b c794f9603" data-form-secondary="true">
                    <input type="hidden" name="state" value="hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8" />
                    <input type="hidden" name="connection" value="google-oauth2" />
                    <button type="submit" className="ca1c710b0 c0132c108 c5f992768" data-provider="google" data-action-button-secondary="true">
                      <span className="cb8afc6a6 c3c12af60" data-provider="google" />
                      <span className="c17890ef2">Sign in with Google</span>
                    </button>
                  </form>

                  <form method="post" data-provider="github" className="c17ed0264 cb2f06e4b c34fab897" data-form-secondary="true">
                    <input type="hidden" name="state" value="hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8" />
                    <input type="hidden" name="connection" value="github" />
                    <button type="submit" className="ca1c710b0 c0132c108 c1c4717e9" data-provider="github" data-action-button-secondary="true">
                      <span className="cb8afc6a6 c3c12af60" data-provider="github" />
                      <span className="c17890ef2">Sign in with GitHub</span>
                    </button>
                  </form>

                  <form method="post" data-provider="linkedin" className="c17ed0264 cb2f06e4b c46040fd0" data-form-secondary="true">
                    <input type="hidden" name="state" value="hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8" />
                    <input type="hidden" name="connection" value="linkedin" />
                    <button type="submit" className="ca1c710b0 c0132c108 ca4fa1303" data-provider="linkedin" data-action-button-secondary="true">
                      <span className="cb8afc6a6 c3c12af60" data-provider="linkedin" />
                      <span className="c17890ef2">Sign in with LinkedIn</span>
                    </button>
                  </form>

                  <form method="post" data-provider="oidc" className="c17ed0264 cb2f06e4b _social-button-container-oidc" data-form-secondary="true">
                    <input type="hidden" name="state" value="hKFo2SBnR0VTX3pBT3o2aTdOeExfZnhPTHZCVmlhZHc4OVA4UaFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIG01NndYS0g1TmF4dnNCZ1NUMXc1S0JibHo3YTQzUmtDo2NpZNkgeFNvN0R0SldtVWVXTTk3d2lHVk1SMzI5d1JxREc5cE8" />
                    <input type="hidden" name="connection" value="SAG-Azure-AD-OIDC" />
                    <button type="submit" className="ca1c710b0 c0132c108 _social-button-oidc" data-provider="oidc" data-action-button-secondary="true">
                      <img 
                        className="cb8afc6a6 ccb92a322" 
                        src="https://cdn.login.siemens.com/public/images/microsoft_entra_id_logo.svg" 
                        alt="Connection icon" 
                      />
                      <span className="c17890ef2">Sign in with Siemens Entra ID</span>
                    </button>
                  </form>

                  <div id="ulp-container-secondary-actions-end" />
                </div>
              </div>
            </div>
          </section>
        </main>

        <footer className="footer">
          <div className="footerLinks">
            <ul>
              <li><a href="https://www.siemens.com/corporate_info" target="_blank" rel="noreferrer">Corporate Information</a></li>
              <li><a href="https://www.siemens.com/privacy" target="_blank" rel="noreferrer">Privacy Notice</a></li>
              <li><a href="https://www.siemens.com/cookie-notice" target="_blank" rel="noreferrer">Cookie Notice</a></li>
              <li><a href="https://www.siemens.com/terms_of_use" target="_blank" rel="noreferrer">Terms of Use</a></li>
              <li><a href="https://www.siemens.com/digital_id_en" target="_blank" rel="noreferrer">Digital ID</a></li>
            </ul>
          </div>
          <div className="footerInfo">
            <div id="footerCopyright" />
          </div>
        </footer>
      </div>
    </div>
  );
}
