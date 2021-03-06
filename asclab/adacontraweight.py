# Copyright 2018 The Google AI Language Team Authors and The HuggingFace Inc. team and authors from University of Illinois at Chicago.
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import os
import logging

import random
import json

import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler

from pytorch_pretrained_bert.tokenization import BertTokenizer
from pytorch_pretrained_bert.modeling import BertForSequenceClassification, PreTrainedBertModel, BertModel
from pytorch_pretrained_bert.optimization import BertAdam

from . import absa_data_utils as data_utils

from . import modelconfig
from . import models

from .trainer import Trainer

logger = logging.getLogger(__name__)

class AdaContraWeight(Trainer):
    """Adaweight use a adaboost-style example weighting function.
    """
    def _evalutate_on_train(self, model, eval_dataloader):
        model.eval()
        all_y_preds=[]
        for step, batch in enumerate(eval_dataloader):
            batch = tuple(t.cuda() for t in batch)
            input_ids, segment_ids, input_mask, _ = batch
            with torch.no_grad():
                logits = model(input_ids, segment_ids, input_mask)
            y_preds = logits.detach().cpu().numpy().argmax(axis=-1)

            all_y_preds.append(y_preds)
        all_y_preds=np.concatenate(all_y_preds) 
        model.train()
        return all_y_preds

    def initial_train_sample_weights(self, train_features):
        total_count = len(train_features)
        contra_count = sum([f.contra for f in train_features])
        noncontra_count = total_count - contra_count
        contra_weight = float(noncontra_count) / total_count
        noncontra_weight = float(contra_count) / total_count
        return torch.tensor([contra_weight if f.contra else noncontra_weight for f in train_features], dtype=torch.float)
    
    def epoch_weight_update(self, args, model, eval_dataloader, all_label_ids, all_sample_weights, train_features):
        """in-place change to all_sample_weights.
        """
        epsilon = 1e-07
        
        all_contra = np.array([f.contra for f in train_features])
        #>>>> perform weight adjustment the end of each epoch.            
        all_y_preds=self._evalutate_on_train(model, eval_dataloader)
        incorrect = np.logical_and(all_y_preds != all_label_ids.numpy(), all_contra)
        estimator_error = np.average(incorrect, weights=all_sample_weights.numpy(), axis=0)
        estimator_weight = np.log(max(epsilon, (1. - estimator_error) + args.factor) / max(epsilon, estimator_error - args.factor) )
        scale = np.exp(estimator_weight * incorrect)
        all_sample_weights.mul_(torch.from_numpy(scale).float() )
        logger.info("sample_weights %s", str(all_sample_weights[:20]) )
        logger.info("****************************************************************")
        logger.info("estimator_error %f", estimator_error)
        logger.info("estimator_weight (should be >0) %f", estimator_weight)
        

class AdaContraUniWeight(Trainer):
    """Adaweight use a adaboost-style example weighting function.
    """
    def _evalutate_on_train(self, model, eval_dataloader):
        model.eval()
        all_y_preds=[]
        for step, batch in enumerate(eval_dataloader):
            batch = tuple(t.cuda() for t in batch)
            input_ids, segment_ids, input_mask, _ = batch
            with torch.no_grad():
                logits = model(input_ids, segment_ids, input_mask)
            y_preds = logits.detach().cpu().numpy().argmax(axis=-1)

            all_y_preds.append(y_preds)
        all_y_preds=np.concatenate(all_y_preds) 
        model.train()
        return all_y_preds

    def initial_train_sample_weights(self, train_features):
        return torch.ones(len(train_features) )/len(train_features)
    
    def epoch_weight_update(self, args, model, eval_dataloader, all_label_ids, all_sample_weights, train_features):
        """in-place change to all_sample_weights.
        """
        epsilon = 1e-07
        
        all_contra = np.array([f.contra for f in train_features])
        #>>>> perform weight adjustment the end of each epoch.            
        all_y_preds=self._evalutate_on_train(model, eval_dataloader)
        incorrect = np.logical_and(all_y_preds != all_label_ids.numpy(), all_contra)
        estimator_error = np.average(incorrect, weights=all_sample_weights.numpy(), axis=0)
        estimator_weight = np.log(max(epsilon, (1. - estimator_error) + args.factor) / max(epsilon, estimator_error - args.factor) )
        scale = np.exp(estimator_weight * incorrect)
        all_sample_weights.mul_(torch.from_numpy(scale).float() )
        logger.info("sample_weights %s", str(all_sample_weights[:20]) )
        logger.info("****************************************************************")
        logger.info("estimator_error %f", estimator_error)
        logger.info("estimator_weight (should be >0) %f", estimator_weight)