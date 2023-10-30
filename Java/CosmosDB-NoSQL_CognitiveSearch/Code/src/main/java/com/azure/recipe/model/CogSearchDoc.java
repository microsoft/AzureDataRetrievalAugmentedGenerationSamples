package com.azure.recipe.model;

import lombok.Data;

import java.util.List;

@Data
public class CogSearchDoc {
    private String id;
    private String name;
    private String description;
    private List<Double> embedding;
}
