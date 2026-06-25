/** useEdgeTriple — subscribe a component to the latest Edge triple for one symbol. */
import { useEffect, useState } from 'react';
import { subscribe, getTriple, getItem } from './edgeTripleStore';

export function useEdgeTriple(symbol) {
  const [, setTick] = useState(0);
  useEffect(() => subscribe(() => setTick((t) => t + 1)), []);
  return { triple: getTriple(symbol), item: getItem(symbol) };
}

export default useEdgeTriple;
