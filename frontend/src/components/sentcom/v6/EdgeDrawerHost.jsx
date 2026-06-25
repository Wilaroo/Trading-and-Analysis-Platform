/** EdgeDrawerHost — mount ONCE in the cockpit; renders the shared EdgeDrawer in
 *  response to openEdgeDrawer() from any EdgeRingForSymbol. */
import React, { useEffect, useState } from 'react';
import EdgeDrawer from './EdgeDrawer';
import { onEdgeDrawer } from './edgeDrawerBus';

export default function EdgeDrawerHost() {
  const [item, setItem] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => onEdgeDrawer((it) => { setItem(it); setOpen(true); }), []);

  return <EdgeDrawer open={open} onClose={() => setOpen(false)} item={item} />;
}
