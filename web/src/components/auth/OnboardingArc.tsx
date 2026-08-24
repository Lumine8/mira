interface OnboardingArcProps {
  dayNumber: number; // 1-7+
}

const ARCS = [
  { day: 1, title: "Day 1", message: "She introduces herself briefly. One question about you." },
  { day: 2, title: "Day 2-3", message: "She references your first conversation. Follows up." },
  { day: 4, title: "Day 4-5", message: "She starts noticing patterns — time of day, topics, mood." },
  { day: 7, title: "Day 7+", message: "The relationship has texture. Things she can do appear naturally." },
];

export default function OnboardingArc({ dayNumber }: OnboardingArcProps) {
  const current = ARCS.find(a => dayNumber <= a.day) || ARCS[ARCS.length - 1];
  
  return (
    <div className="onboarding-arc">
      <div className="onboarding-arc__phase">{current.title}</div>
      <p className="onboarding-arc__message">{current.message}</p>
    </div>
  );
}
