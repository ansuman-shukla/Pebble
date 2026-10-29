/*
 * What a live citizen is doing, in words (the labels, the People panel, the inspector). How its body moves is
 * `motion.ts`.
 */
import type { LiveCitizen } from './live-contract';

/**
 * What someone is doing, in words ("tending the rice paddies", "walking to the well"). Work labels are the
 * engine's task phrases already; walk labels are a place ("the well"), home or a direction ("to the north").
 */
export function activityWords(
  citizen: Pick<LiveCitizen, 'activity' | 'action_label' | 'cause_of_death'>,
): string {
  const { activity, action_label: label, cause_of_death: cause } = citizen;
  const with_ = (verb: string, joint = ' ') =>
    label ? `${verb}${joint}${label}` : verb;
  switch (activity) {
    case 'idle':
      return 'standing about';
    case 'walking':
      return with_(
        'walking',
        label === 'home' || label.startsWith('to ') ? ' ' : ' to ',
      );
    case 'running':
      return with_('running');
    case 'hunting':
      return with_('hunting');
    case 'fishing':
      return 'fishing';
    case 'tending_fire':
      return with_('tending', ' ');
    case 'sleeping':
      return 'asleep';
    case 'resting':
      return with_('resting', ' by ');
    case 'gathering':
      return with_('gathering');
    case 'working':
      return label || 'working';
    case 'eating':
      return with_('eating');
    case 'drinking':
      return with_('drinking', ' at ');
    case 'talking':
      return with_('talking', ' to ');
    case 'dead':
      return cause ? `dead (${cause})` : 'dead';
  }
}
