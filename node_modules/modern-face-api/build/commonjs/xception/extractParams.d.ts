import type { ParamMapping } from '../common/types';
import type { TinyXceptionParams } from './types';
export declare function extractParams(weights: Float32Array, numMainBlocks: number): {
    params: TinyXceptionParams;
    paramMappings: ParamMapping[];
};
