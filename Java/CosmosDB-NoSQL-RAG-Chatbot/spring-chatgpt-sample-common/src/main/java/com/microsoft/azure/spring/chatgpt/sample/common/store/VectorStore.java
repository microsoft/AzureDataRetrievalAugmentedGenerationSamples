package com.microsoft.azure.spring.chatgpt.sample.common.store;

import java.util.List;

public interface VectorStore {
    void saveDocument(String key, CosmosEntity doc);

    CosmosEntity getDocument(String key);

    void removeDocument(String key);

    List<CosmosEntity> searchTopKNearest(List<Double> embedding, int k);

    List<CosmosEntity> searchTopKNearest(List<Double> embedding, int k, double cutOff);
}
