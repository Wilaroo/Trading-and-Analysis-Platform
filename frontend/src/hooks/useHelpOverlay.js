/**
 * useHelpOverlay — global press-? hover layer.
 *
 * Press `?` (Shift+/) anywhere on the page (not while typing in an
 * input) to enter "help mode". While active:
 *
 *   - Adds `data-help-mode="on"` to <body>. CSS in App.css picks this
 *     up and reveals a small ❓ chip on every element with a
 *     `data-help-id` attribute.
 *   - Click any chip → opens the GlossaryDrawer at that term.
 *   - Press ? again, Esc, or click outside → exit help mode.
 *
 * Side-effect-only hook: returns nothing. Mount once in the app root.
 */

import { useEffect } from 'react';
import { openGlossary } from '../components/GlossaryDrawer';

const ATTR = 'data-help-mode';
const TARGET_ATTR = 'data-help-id';

function _isTypingTarget(t) {
  if (!t) return false;
  const tag = String(t.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (t.isContentEditable) return true;
  return false;
}

export function useHelpOverlay() {
  useEffect(() => {
    const exit = () => {
      document.body.setAttribute(ATTR, 'off');
    };
    const enter = () => {
      document.body.setAttribute(ATTR, 'on');
    };
    const toggle = () => {
      const curr = document.body.getAttribute(ATTR);
      if (curr === 'on') exit();
      else enter();
    };

    const onKey = (e) => {
      // Real keyboards on US layout produce e.key === '?' on Shift+/, but
      // some IMEs / synthetic events emit '/' with shiftKey set. Accept both.
      const isHelpKey =
        (e.key === '?' || (e.key === '/' && e.shiftKey)) && !_isTypingTarget(e.target);
      if (isHelpKey) {
        e.preventDefault();
        toggle();
      } else if (e.key === 'Escape' && document.body.getAttribute(ATTR) === 'on') {
        exit();
      }
    };

    // Click on a [data-help-id] element while in help mode → open glossary
    const onClick = (e) => {
      if (document.body.getAttribute(ATTR) !== 'on') return;
      // Find nearest ancestor with data-help-id
      let node = e.target;
      while (node && node !== document.body) {
        if (node.getAttribute && node.getAttribute(TARGET_ATTR)) {
          e.preventDefault();
          e.stopPropagation();
          const termId = node.getAttribute(TARGET_ATTR);
          openGlossary(termId);
          exit();
          return;
        }
        node = node.parentNode;
      }
    };

    window.addEventListener('keydown', onKey);
    document.addEventListener('click', onClick, true); // capture phase, beats button onClicks

    // Initialise
    exit();

    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('click', onClick, true);
      exit();
    };
  }, []);
}

export default useHelpOverlay;
