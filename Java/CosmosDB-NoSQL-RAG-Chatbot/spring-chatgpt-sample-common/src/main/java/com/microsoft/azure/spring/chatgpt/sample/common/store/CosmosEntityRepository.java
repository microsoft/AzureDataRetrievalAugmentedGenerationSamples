package com.microsoft.azure.spring.chatgpt.sample.common.store;
import com.azure.spring.data.cosmos.repository.CosmosRepository;
import com.azure.spring.data.cosmos.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import java.util.ArrayList;

@Repository
public interface CosmosEntityRepository extends CosmosRepository<CosmosEntity, String> {
    @Query(value = "SELECT TOP 3 c.id, c.embedding, c.hash, c.text, VectorDistance(c.embedding,@embedding) AS SimilarityScore FROM c ORDER BY VectorDistance(c.embedding,@embedding)")
    ArrayList<CosmosEntity> vectorSearch(@Param("embedding") Object embedding);

    @Query(value = "SELECT c.id FROM c where c.id = @id")
    ArrayList<CosmosEntity> findRecord(@Param("embedding") String id);
}