// Trading utility functions shared across components

export const playSound = (type = 'alert') => {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    
    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    
    if (type === 'fill') {
      // Order fill sound - pleasant ding
      oscillator.frequency.setValueAtTime(880, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(1100, audioContext.currentTime + 0.1);
      oscillator.type = 'sine';
      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.3);
    } else if (type === 'alert') {
      // Price alert sound - attention-grabbing
      oscillator.frequency.setValueAtTime(660, audioContext.currentTime);
      oscillator.frequency.setValueAtTime(880, audioContext.currentTime + 0.15);
      oscillator.frequency.setValueAtTime(660, audioContext.currentTime + 0.3);
      oscillator.type = 'square';
      gainNode.gain.setValueAtTime(0.2, audioContext.currentTime);
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.4);
      oscillator.start(audioContext.currentTime);
      oscillator.stop(audioContext.currentTime + 0.4);
    }
  } catch (e) {
    console.log('Sound not supported');
  }
};

export const formatPrice = (price) => {
  if (!price && price !== 0) return '--';
  return price.toFixed(2);
};

export const formatPercent = (pct) => {
  if (!pct && pct !== 0) return '--';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
};

export const formatVolume = (vol) => {
  if (!vol) return '--';
  if (vol >= 1e9) return `${(vol / 1e9).toFixed(1)}B`;
  if (vol >= 1e6) return `${(vol / 1e6).toFixed(1)}M`;
  if (vol >= 1e3) return `${(vol / 1e3).toFixed(1)}K`;
  return vol.toString();
};

export const formatCurrency = (val) => {
  if (!val && val !== 0) return '--';
  return val.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
};

export const formatMarketCap = (cap) => {
  if (!cap) return '--';
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(2)}T`;
  if (cap >= 1e9) return `$${(cap / 1e9).toFixed(1)}B`;
  if (cap >= 1e6) return `$${(cap / 1e6).toFixed(1)}M`;
  return `$${cap.toLocaleString()}`;
};

export const getScoreColor = (score) => {
  if (score >= 80) return 'text-green-400';
  if (score >= 60) return 'text-cyan-400';
  if (score >= 40) return 'text-yellow-400';
  return 'text-red-400';
};

export const getGradeColor = (grade) => {
  if (!grade) return 'bg-zinc-600 text-white';
  if (grade.startsWith('A')) return 'bg-green-500 text-black';
  if (grade.startsWith('B')) return 'bg-cyan-500 text-black';
  if (grade.startsWith('C')) return 'bg-yellow-500 text-black';
  return 'bg-red-500 text-white';
};

export const getBiasColor = (bias) => {
  if (bias === 'BULLISH') return 'bg-green-500/20 text-green-400';
  if (bias === 'BEARISH') return 'bg-red-500/20 text-red-400';
  return 'bg-zinc-500/20 text-zinc-400';
};
